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
    def __init__(self, proxy_list=None, max_threads=50, max_valid_rng=50):
        self.ua = UserAgent()
        self.max_threads = max_threads
        self.max_valid_rng = max_valid_rng
        self.session = requests.Session()
        self.proxy_list = proxy_list or []
        self.current_proxy_index = 0
        self.lock = threading.Lock()
        self.found_urls = set()  # Untuk mencegah duplikat
        
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
            'movable_type_v4': 'movable_type_v4.txt'
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
    
    def generate_random_ips(self, base_ip, max_valid=None):
        """Menghasilkan IP acak dari base IP dengan 2 digit terakhir random"""
        if max_valid is None:
            max_valid = self.max_valid_rng
            
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
        
        print(f"[*] Total {len(valid_ips)} IP valid ditemukan")
        return valid_ips
    
    def reverse_ip_tntcode(self, ip):
        """Reverse IP menggunakan tntcode.com (dengan proxy)"""
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
        """Reverse IP menggunakan hackertarget.com (dengan proxy)"""
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
        """Memeriksa keberadaan rsd.xml (TANPA PROXY untuk kecepatan)"""
        paths = ['/rsd.xml', '/blog/rsd.xml']
        
        for path in paths:
            try:
                url = f"http://{domain}{path}"
                headers = self.headers.copy()
                headers["User-Agent"] = self.ua.random
                
                # TANPA PROXY - langsung koneksi
                response = self.session.get(url, headers=headers, timeout=10)
                
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
                
                # TANPA PROXY - langsung koneksi
                response = self.session.get(url, headers=headers, timeout=10)
                
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
        
        # Cari API link (mt-xmlrpc.cgi)
        api_match = re.search(r'<api[^>]*apiLink="([^"]+)"[^>]*>', rsd_content, re.IGNORECASE)
        if api_match:
            info['api_link'] = api_match.group(1).strip()
            
        return info
    
    def check_mt_endpoints(self, domain, mt_info):
        """Memeriksa endpoint Movable Type dari rsd.xml (TANPA PROXY)"""
        results = []
        
        # Cek mt-xmlrpc.cgi dari apiLink
        if mt_info['api_link']:
            # Buat URL lengkap untuk mt-xmlrpc.cgi
            xmlrpc_urls = []
            
            # Jika api_link sudah URL lengkap
            if mt_info['api_link'].startswith('http'):
                xmlrpc_urls.append(mt_info['api_link'])
            else:
                # Jika path relatif, coba dengan http dan https
                xmlrpc_urls.append(f"http://{domain}{mt_info['api_link']}")
                xmlrpc_urls.append(f"https://{domain}{mt_info['api_link']}")
            
            for xmlrpc_url in xmlrpc_urls:
                try:
                    # TANPA PROXY - langsung koneksi
                    headers = self.headers.copy()
                    headers["User-Agent"] = self.ua.random
                    
                    response = self.session.get(xmlrpc_url, headers=headers, timeout=10, allow_redirects=False)
                    
                    # Cek apakah versi 4
                    is_v4 = mt_info.get('version') and mt_info['version'].startswith('4')
                    
                    # Simpan jika kode 403, 411, 405
                    if response.status_code in [403, 411, 405]:
                        # Cek duplikat
                        url_key = f"{xmlrpc_url}|{response.status_code}"
                        if url_key in self.found_urls:
                            continue
                        
                        self.found_urls.add(url_key)
                        
                        # Simpan ke file movable_type.txt
                        with open(self.output_files['movable_type'], 'a') as f:
                            f.write(f"{xmlrpc_url}\n")
                        
                        # Tampilkan dengan path lengkap
                        display_url = xmlrpc_url.replace('http://', '').replace('https://', '')
                        print(f"[+] Movable Type ditemukan: {display_url} (Status: {response.status_code})")
                        
                        result = {
                            'domain': domain,
                            'xmlrpc_url': xmlrpc_url,
                            'xmlrpc_status': response.status_code,
                            'version': mt_info.get('version'),
                            'is_v4': is_v4
                        }
                        
                        results.append(result)
                    
                    # Untuk versi 4, SELALU cek mt-upgrade.cgi di path yang sama
                    if is_v4:
                        # Ganti mt-xmlrpc.cgi dengan mt-upgrade.cgi di path yang sama persis
                        upgrade_url = xmlrpc_url.replace('mt-xmlrpc.cgi', 'mt-upgrade.cgi')
                        
                        # Pastikan upgrade_url berbeda dari xmlrpc_url
                        if upgrade_url != xmlrpc_url:
                            try:
                                # TANPA PROXY
                                upgrade_response = self.session.get(upgrade_url, headers=headers, timeout=10, allow_redirects=False)
                                if upgrade_response.status_code == 200:
                                    upgrade_key = f"{upgrade_url}|200"
                                    if upgrade_key not in self.found_urls:
                                        self.found_urls.add(upgrade_key)
                                        
                                        # Simpan ke file movable_type_v4.txt
                                        with open(self.output_files['movable_type_v4'], 'a') as f:
                                            f.write(f"{upgrade_url}\n")
                                        
                                        display_upgrade = upgrade_url.replace('http://', '').replace('https://', '')
                                        print(f"[!] Movable Type v4 dengan mt-upgrade.cgi: {display_upgrade}")
                            except:
                                pass
                    
                except Exception as e:
                    continue
        
        return results
    
    def scan_domain(self, domain):
        """Scan satu domain untuk Movable Type (TANPA PROXY)"""
        try:
            # Cek rsd.xml
            rsd_content, rsd_url = self.check_rsd_xml(domain)
            
            if rsd_content:
                mt_info = self.extract_mt_info(rsd_content)
                
                if mt_info['engine'] and 'movable type' in mt_info['engine'].lower():
                    results = self.check_mt_endpoints(domain, mt_info)
                    return results
        except Exception as e:
            pass
        return []
    
    def process_ip(self, ip):
        """Proses satu IP untuk reverse IP (dengan proxy) dan scan (tanpa proxy)"""
        print(f"\n[*] Memproses IP: {ip}")
        
        # REVERSE IP - MENGGUNAKAN PROXY
        print("[*] Reverse IP dengan proxy...")
        domains_tnt = self.reverse_ip_tntcode(ip)
        print(f"[+] TNTCode: {len(domains_tnt)} domain ditemukan")
        
        domains_ht = self.reverse_ip_hackertarget(ip)
        print(f"[+] HackerTarget: {len(domains_ht)} domain ditemukan")
        
        # Gabungkan dan hapus duplikat
        all_domains = list(set(domains_tnt + domains_ht))
        
        if all_domains:
            print(f"[+] Total domain unik: {len(all_domains)}")
            
            # SCAN DOMAIN - TANPA PROXY UNTUK KECEPATAN
            print("[*] Scanning domain tanpa proxy untuk kecepatan maksimal...")
            found_count = 0
            with ThreadPoolExecutor(max_workers=50) as executor:  # Thread lebih banyak karena tanpa proxy
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
        valid_ips = self.generate_random_ips(base_ip)
        
        if valid_ips:
            print(f"\n[*] Memulai scan untuk {len(valid_ips)} IP valid...")
            
            with ThreadPoolExecutor(max_workers=self.max_threads) as executor:
                futures = [executor.submit(self.process_ip, ip) for ip in valid_ips]
                for future in as_completed(futures):
                    try:
                        future.result()
                    except Exception as e:
                        print(f"[-] Error: {e}")


def download_proxy_list():
    """Download proxy list dari GitHub langsung ke memory"""
    proxy_url = "https://raw.githubusercontent.com/proxifly/free-proxy-list/refs/heads/main/proxies/all/data.txt"
    
    try:
        print("[*] Mendownload proxy list...")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        response = requests.get(proxy_url, headers=headers, timeout=30)
        
        if response.status_code == 200:
            # Ambil semua proxy (format sudah sesuai: protocol://ip:port)
            proxies = [line.strip() for line in response.text.split('\n') if line.strip()]
            
            # Filter hanya proxy yang valid (minimal ada protocol://)
            valid_proxies = [p for p in proxies if '://' in p]
            
            print(f"[+] Berhasil mendapatkan {len(valid_proxies)} proxy online")
            return valid_proxies
        else:
            print(f"[-] Gagal download proxy, status code: {response.status_code}")
            return []
            
    except Exception as e:
        print(f"[-] Error download proxy: {str(e)[:50]}")
        return []

def get_proxies():
    """Mendapatkan proxy - PRIORITAS ONLINE, tanpa file sama sekali"""
    print("[*] Mencoba mengambil proxy online...")
    online_proxies = download_proxy_list()
    
    if online_proxies:
        print(f"[+] Menggunakan {len(online_proxies)} proxy online")
        return online_proxies
    
    # Jika tidak ada proxy online, jalankan tanpa proxy
    print("[!] Tidak ada proxy online, melanjutkan tanpa proxy...")
    return []

def main():
    print("""
    ╔══════════════════════════════════════════╗
    ║     Movable Type Mass Scanner v1.6       ║
    ║   Proxy Only for Reverse IP, No Proxy    ║
    ║          for Faster Domain Scan          ║
    ╚══════════════════════════════════════════╝
    """)
    
    # Langsung ambil proxy online, tanpa tanya, tanpa file
    proxies = get_proxies()
    
    # Setup scanner
    max_valid_rng = 50
    
    print("\nPilih metode input:")
    print("1. Scan dari file list IP")
    print("2. Scan dengan RNG IP (2 digit terakhir random)")
    
    choice = input("\nPilihan (1/2): ").strip()
    
    if choice == '1':
        filename = input("Masukkan nama file list IP: ").strip()
        if filename:
            scanner = MovableTypeScanner(proxy_list=proxies, max_threads=50, max_valid_rng=max_valid_rng)
            scanner.scan_from_file(filename)
            
    elif choice == '2':
        base_ip = input("Masukkan base IP (tanpa 2 digit terakhir, contoh: 157.7.44): ").strip()
        if base_ip:
            # Tambahkan .1 jika hanya 3 oktet
            if base_ip.count('.') == 3:
                base_ip = base_ip
            elif base_ip.count('.') == 2:
                base_ip = base_ip + '.1'
            
            # Tanya jumlah IP valid yang diinginkan
            try:
                max_valid_input = input("Jumlah IP valid yang ingin dicari (default 50): ").strip()
                if max_valid_input:
                    max_valid_rng = int(max_valid_input)
            except:
                print("[*] Menggunakan default 50")
            
            scanner = MovableTypeScanner(proxy_list=proxies, max_threads=50, max_valid_rng=max_valid_rng)
            scanner.scan_random_ips(base_ip)
            
    else:
        print("[!] Pilihan tidak valid!")
        return
    
    print("\n[*] Scan selesai!")
    print(f"[*] Hasil disimpan di:")
    print(f"    - {scanner.output_files['movable_type']} (URL mt-xmlrpc.cgi dari rsd.xml dengan status 403/411/405)")
    print(f"    - {scanner.output_files['movable_type_v4']} (URL mt-upgrade.cgi untuk versi 4 dengan status 200)")

if __name__ == "__main__":
    main()
