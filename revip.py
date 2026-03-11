import requests
import re
import time
import random
import threading
from queue import Queue
from fake_useragent import UserAgent
from urllib.parse import urlparse
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed

class MovableTypeScanner:
    def __init__(self, proxy_list=None, max_threads=50):
        self.ua = UserAgent()
        self.max_threads = max_threads
        self.session = requests.Session()
        self.proxy_list = proxy_list or []
        self.current_proxy_index = 0
        self.lock = threading.Lock()
        
        # Headers untuk requests
        self.headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate",
            "DNT": "1",
            "Connection": "close"
        }
        
        # File output
        self.output_files = {
            'movable_type': 'movable_type.txt',
            'movable_type_v4': 'movable_type_v4.txt',
            'domains': 'domains.txt',
            'valid_ips': 'valid_ips.txt'
        }
        
    def get_proxy(self):
        """Mendapatkan proxy secara bergantian"""
        if not self.proxy_list:
            return None
            
        with self.lock:
            proxy = self.proxy_list[self.current_proxy_index]
            self.current_proxy_index = (self.current_proxy_index + 1) % len(self.proxy_list)
            return {"http": proxy, "https": proxy}
    
    def check_ip_valid(self, ip):
        """Memeriksa apakah IP valid dengan timeout singkat"""
        try:
            socket.gethostbyaddr(ip)
            return True
        except:
            return False
    
    def generate_random_ips(self, base_ip, max_valid=50):
        """Menghasilkan IP acak dari base IP dengan 2 digit terakhir random"""
        base_parts = base_ip.split('.')
        if len(base_parts) != 4:
            print("[!] Format IP tidak valid!")
            return []
        
        base = '.'.join(base_parts[:3]) + '.'
        valid_ips = []
        attempted = set()
        
        print(f"[*] Mencari {max_valid} IP valid dari {base}[1-254]...")
        
        while len(valid_ips) < max_valid and len(attempted) < 254:
            last_octet = random.randint(1, 254)
            ip = base + str(last_octet)
            
            if ip in attempted:
                continue
                
            attempted.add(ip)
            
            if self.check_ip_valid(ip):
                valid_ips.append(ip)
                print(f"[+] IP Valid ditemukan: {ip} ({len(valid_ips)}/{max_valid})")
                
        # Simpan IP valid
        with open(self.output_files['valid_ips'], 'a') as f:
            for ip in valid_ips:
                f.write(f"{ip}\n")
                
        return valid_ips
    
    def reverse_ip_tntcode(self, ip):
        """Reverse IP menggunakan tntcode.com"""
        try:
            url = f"https://domains.tntcode.com/ip/{ip}"
            headers = self.headers.copy()
            headers["User-Agent"] = self.ua.random
            
            proxies = self.get_proxy()
            response = self.session.get(url, headers=headers, proxies=proxies, timeout=30)
            
            domains = re.findall(r'<a href="/domain/(.+?)"', response.text)
            return domains
        except Exception as e:
            print(f"[-] TNTCode error untuk {ip}: {str(e)[:50]}")
            return []
    
    def reverse_ip_hackertarget(self, ip):
        """Reverse IP menggunakan hackertarget.com"""
        try:
            url = f"https://api.hackertarget.com/reverseiplookup/?q={ip}"
            headers = self.headers.copy()
            headers["User-Agent"] = self.ua.random
            
            proxies = self.get_proxy()
            response = self.session.get(url, headers=headers, proxies=proxies, timeout=30)
            
            if response.text and "error" not in response.text.lower():
                return response.text.strip().split('\n')
            return []
        except Exception as e:
            print(f"[-] HackerTarget error untuk {ip}: {str(e)[:50]}")
            return []
    
    def check_rsd_xml(self, domain):
        """Memeriksa keberadaan rsd.xml"""
        paths = ['/rsd.xml', '/blog/rsd.xml']
        
        for path in paths:
            try:
                url = f"http://{domain}{path}"
                headers = self.headers.copy()
                headers["User-Agent"] = self.ua.random
                
                proxies = self.get_proxy()
                response = self.session.get(url, headers=headers, proxies=proxies, timeout=15)
                
                if response.status_code == 200 and 'rsd' in response.text.lower():
                    return response.text, url
            except:
                continue
        
        # Coba HTTPS
        for path in paths:
            try:
                url = f"https://{domain}{path}"
                headers = self.headers.copy()
                headers["User-Agent"] = self.ua.random
                
                proxies = self.get_proxy()
                response = self.session.get(url, headers=headers, proxies=proxies, timeout=15)
                
                if response.status_code == 200 and 'rsd' in response.text.lower():
                    return response.text, url
            except:
                continue
                
        return None, None
    
    def extract_mt_info(self, rsd_content):
        """Mengekstrak informasi Movable Type dari rsd.xml"""
        info = {
            'engine': None,
            'api_link': None,
            'version': None
        }
        
        # Cari engine name
        engine_match = re.search(r'<engineName>(.+?)</engineName>', rsd_content, re.IGNORECASE)
        if engine_match:
            info['engine'] = engine_match.group(1)
            if 'movable type' in info['engine'].lower():
                version_match = re.search(r'(\d+\.\d+)', info['engine'])
                if version_match:
                    info['version'] = version_match.group(1)
        
        # Cari API link
        api_match = re.search(r'<apiLink>(.+?)</apiLink>', rsd_content, re.IGNORECASE)
        if api_match:
            info['api_link'] = api_match.group(1)
            
        return info
    
    def check_mt_endpoints(self, domain, mt_info):
        """Memeriksa endpoint Movable Type"""
        results = []
        
        # Cek mt-xmlrpc.cgi
        if mt_info['api_link']:
            xmlrpc_url = mt_info['api_link']
        else:
            # Coba tebak path umum
            xmlrpc_url = f"http://{domain}/mt-xmlrpc.cgi"
        
        try:
            proxies = self.get_proxy()
            headers = self.headers.copy()
            headers["User-Agent"] = self.ua.random
            
            response = self.session.get(xmlrpc_url, headers=headers, proxies=proxies, timeout=15, allow_redirects=False)
            
            # Simpan jika kode 403, 411, 405
            if response.status_code in [403, 411, 405]:
                result = {
                    'domain': domain,
                    'xmlrpc_url': xmlrpc_url,
                    'xmlrpc_status': response.status_code,
                    'version': mt_info.get('version'),
                    'is_v4': False
                }
                results.append(result)
                
                print(f"[+] Movable Type ditemukan: {domain} (Status: {response.status_code})")
                
                # Cek apakah versi 4
                if mt_info.get('version') and mt_info['version'].startswith('4'):
                    result['is_v4'] = True
                    
                    # Cek mt-upgrade.cgi
                    upgrade_url = f"http://{domain}/mt-upgrade.cgi"
                    upgrade_response = self.session.get(upgrade_url, headers=headers, proxies=proxies, timeout=15, allow_redirects=False)
                    
                    if upgrade_response.status_code == 200:
                        print(f"[!] Movable Type v4 dengan mt-upgrade.cgi: {domain}")
                        with open(self.output_files['movable_type_v4'], 'a') as f:
                            f.write(f"{domain} | XMLRPC: {xmlrpc_url} | Upgrade: {upgrade_url}\n")
                        
        except Exception as e:
            pass
            
        return results
    
    def scan_domain(self, domain):
        """Scan satu domain untuk Movable Type"""
        try:
            # Cek rsd.xml
            rsd_content, rsd_url = self.check_rsd_xml(domain)
            
            if rsd_content:
                mt_info = self.extract_mt_info(rsd_content)
                
                if mt_info['engine'] and 'movable type' in mt_info['engine'].lower():
                    results = self.check_mt_endpoints(domain, mt_info)
                    
                    # Simpan hasil
                    for result in results:
                        with open(self.output_files['movable_type'], 'a') as f:
                            line = f"{domain} | XMLRPC: {result['xmlrpc_url']} (Status: {result['xmlrpc_status']})"
                            if result.get('version'):
                                line += f" | Version: {result['version']}"
                            f.write(line + "\n")
                    
                    return results
        except Exception as e:
            pass
        return []
    
    def process_ip(self, ip):
        """Proses satu IP untuk reverse IP dan scan"""
        print(f"\n[*] Memproses IP: {ip}")
        
        # Reverse IP dari kedua tools
        domains_tnt = self.reverse_ip_tntcode(ip)
        print(f"[+] TNTCode: {len(domains_tnt)} domain ditemukan")
        
        domains_ht = self.reverse_ip_hackertarget(ip)
        print(f"[+] HackerTarget: {len(domains_ht)} domain ditemukan")
        
        # Gabungkan dan hapus duplikat
        all_domains = list(set(domains_tnt + domains_ht))
        
        if all_domains:
            print(f"[+] Total domain unik: {len(all_domains)}")
            
            # Simpan domain
            with open(self.output_files['domains'], 'a') as f:
                for domain in all_domains:
                    f.write(f"{domain}\n")
            
            # Scan setiap domain untuk Movable Type
            found_count = 0
            with ThreadPoolExecutor(max_workers=20) as executor:
                futures = [executor.submit(self.scan_domain, domain) for domain in all_domains]
                for future in as_completed(futures):
                    results = future.result()
                    if results:
                        found_count += len(results)
            
            print(f"[+] Selesai IP {ip}: {found_count} Movable Type ditemukan")
        else:
            print(f"[-] Tidak ada domain ditemukan untuk IP {ip}")
    
    def scan_from_file(self, filename):
        """Scan dari file list IP"""
        try:
            with open(filename, 'r') as f:
                ips = [line.strip() for line in f if line.strip()]
            
            print(f"[*] Memuat {len(ips)} IP dari file {filename}")
            
            with ThreadPoolExecutor(max_workers=self.max_threads) as executor:
                futures = [executor.submit(self.process_ip, ip) for ip in ips]
                for future in as_completed(futures):
                    try:
                        future.result()
                    except Exception as e:
                        print(f"[-] Error: {e}")
                        
        except Exception as e:
            print(f"[!] Error membaca file: {e}")
    
    def scan_random_ips(self, base_ip):
        """Scan dengan IP random dari base IP"""
        valid_ips = self.generate_random_ips(base_ip, max_valid=50)
        
        if valid_ips:
            print(f"\n[*] Memulai scan untuk {len(valid_ips)} IP valid...")
            
            with ThreadPoolExecutor(max_workers=self.max_threads) as executor:
                futures = [executor.submit(self.process_ip, ip) for ip in valid_ips]
                for future in as_completed(futures):
                    try:
                        future.result()
                    except Exception as e:
                        print(f"[-] Error: {e}")

def load_proxies(filename='proxies.txt'):
    """Memuat daftar proxy dari file"""
    try:
        with open(filename, 'r') as f:
            proxies = [line.strip() for line in f if line.strip()]
            if proxies:
                print(f"[+] {len(proxies)} proxy dimuat")
                return proxies
    except:
        pass
    print("[!] Tidak ada proxy, melanjutkan tanpa proxy...")
    return []

def main():
    print("""
    ╔══════════════════════════════════════════╗
    ║     Movable Type Mass Scanner v1.0       ║
    ║        Unlimited Scan Nonstop             ║
    ╚══════════════════════════════════════════╝
    """)
    
    # Load proxy jika ada
    proxies = load_proxies()
    scanner = MovableTypeScanner(proxy_list=proxies, max_threads=50)
    
    print("\nPilih metode input:")
    print("1. Scan dari file list IP")
    print("2. Scan dengan RNG IP (2 digit terakhir random)")
    
    choice = input("\nPilihan (1/2): ").strip()
    
    if choice == '1':
        filename = input("Masukkan nama file list IP: ").strip()
        if filename:
            scanner.scan_from_file(filename)
            
    elif choice == '2':
        base_ip = input("Masukkan base IP (tanpa 2 digit terakhir, contoh: 157.7.44.1): ").strip()
        if base_ip:
            scanner.scan_random_ips(base_ip)
            
    else:
        print("[!] Pilihan tidak valid!")
        return
    
    print("\n[*] Scan selesai!")
    print(f"[*] Hasil disimpan di:")
    print(f"    - {scanner.output_files['movable_type']} (Semua Movable Type)")
    print(f"    - {scanner.output_files['movable_type_v4']} (Movable Type v4 dengan mt-upgrade.cgi)")
    print(f"    - {scanner.output_files['domains']} (Semua domain dari reverse IP)")
    print(f"    - {scanner.output_files['valid_ips']} (IP valid dari RNG)")

if __name__ == "__main__":
    main()
