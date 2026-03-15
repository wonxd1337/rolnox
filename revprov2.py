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
    
    def generate_random_ips_from_base(self, base_ip, rng_mode="2digit_last", max_valid=None):
        """
        Menghasilkan IP acak dengan merandom digit terakhir dari oktet ke-4
        
        Args:
            base_ip: IP lengkap contoh (157.7.44.176)
            rng_mode: 
                - "2digit_last": random 2 digit terakhir dari oktet ke-4 (puluhan dan satuan)
                - "3digit_last": random seluruh oktet ke-4 (1-254)
            max_valid: Jumlah IP valid yang diinginkan
        """
        if max_valid is None:
            max_valid = self.max_valid_rng
            
        base_parts = base_ip.split('.')
        if len(base_parts) != 4:
            print("[!] Format IP tidak valid! Gunakan format: x.x.x.x")
            return []
        
        # 3 oktet pertama tetap
        prefix = '.'.join(base_parts[:3])
        
        # Oktet ke-4 sebagai referensi
        last_octet = int(base_parts[3])
        
        valid_ips = []
        attempted = set()
        
        if rng_mode == "2digit_last":
            # Random 2 digit terakhir dari oktet ke-4
            # Contoh: 176 -> range 100-199 (digit ratusan tetap, puluhan dan satuan random)
            base_value = (last_octet // 100) * 100  # Ambil digit ratusan
            start_range = base_value
            end_range = base_value + 99
            
            # Pastikan range valid (1-254)
            if start_range < 1:
                start_range = 1
            if end_range > 254:
                end_range = 254
            
            max_possible = end_range - start_range + 1
            
            print(f"\n[*] Mode RNG: 2 digit terakhir oktet ke-4")
            print(f"[*] Base IP: {base_ip}")
            print(f"[*] 3 oktet tetap: {prefix}")
            print(f"[*] Range oktet ke-4: {start_range}-{end_range} (berdasarkan digit ratusan {base_value//100})")
            print(f"[*] Mencari {max_valid} IP valid...")
            
            while len(valid_ips) < max_valid and len(attempted) < max_possible:
                # Random 2 digit terakhir (0-99)
                last_two_digits = random.randint(0, 99)
                new_last_octet = base_value + last_two_digits
                
                # Pastikan dalam range valid
                if new_last_octet < 1 or new_last_octet > 254:
                    continue
                
                # Skip jika sama dengan IP asli
                if new_last_octet == last_octet:
                    continue
                
                ip = f"{prefix}.{new_last_octet}"
                
                if ip in attempted:
                    continue
                    
                attempted.add(ip)
                
                if self.check_ip_valid(ip):
                    valid_ips.append(ip)
                    print(f"[+] IP Valid: {ip} (dari range {start_range}-{end_range}) [{len(valid_ips)}/{max_valid}]")
        
        elif rng_mode == "3digit_last":
            # Random seluruh oktet ke-4 (1-254)
            print(f"\n[*] Mode RNG: 3 digit terakhir (seluruh oktet ke-4)")
            print(f"[*] Base IP: {base_ip}")
            print(f"[*] 3 oktet tetap: {prefix}")
            print(f"[*] Range oktet ke-4: 1-254")
            print(f"[*] Mencari {max_valid} IP valid...")
            
            max_possible = 254
            
            while len(valid_ips) < max_valid and len(attempted) < max_possible:
                # Random seluruh oktet ke-4 (1-254)
                new_last_octet = random.randint(1, 254)
                
                # Skip jika sama dengan IP asli
                if new_last_octet == last_octet:
                    continue
                
                ip = f"{prefix}.{new_last_octet}"
                
                if ip in attempted:
                    continue
                    
                attempted.add(ip)
                
                if self.check_ip_valid(ip):
                    valid_ips.append(ip)
                    print(f"[+] IP Valid: {ip} (range 1-254) [{len(valid_ips)}/{max_valid}]")
        
        print(f"\n[*] Total {len(valid_ips)} IP valid ditemukan dari {len(attempted)} percobaan")
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
            with ThreadPoolExecutor(max_workers=50) as executor:
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
    
    def scan_random_ips_from_base(self, base_ip, rng_mode="2digit_last"):
        """Scan dengan IP random dari base IP (merandom 2 atau 3 digit terakhir oktet ke-4)"""
        valid_ips = self.generate_random_ips_from_base(base_ip, rng_mode)
        
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
    ╔══════════════════════════════════════════════╗
    ║        Movable Type Mass Scanner v2.0        ║
    ║     Proxy Only for Reverse IP, No Proxy      ║
    ║            for Faster Domain Scan            ║
    ║   Fitur RNG 2-3 Digit Terakhir Oktet Ke-4    ║
    ╚══════════════════════════════════════════════╝
    """)
    
    # Langsung ambil proxy online, tanpa tanya, tanpa file
    proxies = get_proxies()
    
    # Setup scanner
    max_valid_rng = 50
    
    print("\nPilih metode input:")
    print("1. Scan dari file list IP")
    print("2. Scan dengan RNG IP (random 2-3 digit terakhir oktet ke-4)")
    
    choice = input("\nPilihan (1/2): ").strip()
    
    if choice == '1':
        filename = input("Masukkan nama file list IP: ").strip()
        if filename:
            scanner = MovableTypeScanner(proxy_list=proxies, max_threads=50, max_valid_rng=max_valid_rng)
            scanner.scan_from_file(filename)
            
    elif choice == '2':
        print("\n" + "="*60)
        print("PILIH MODE RNG (Random Digit Terakhir Oktet Ke-4):")
        print("="*60)
        print("1. Random 2 digit terakhir (puluhan dan satuan)")
        print("   Contoh: 157.7.44.176 -> 157.7.44.1XX (digit ratusan tetap)")
        print("   Range: tergantung digit ratusan (max 100 kemungkinan)")
        print("\n2. Random 3 digit terakhir (seluruh oktet ke-4)")
        print("   Contoh: 157.7.44.176 -> 157.7.44.[1-254]")
        print("   Range: 1-254 (254 kemungkinan)")
        print("="*60)
        
        rng_choice = input("\nPilihan mode RNG (1/2): ").strip()
        
        if rng_choice == '1':
            rng_mode = "2digit_last"
            print("\n[✓] Mode: Random 2 digit terakhir oktet ke-4")
        elif rng_choice == '2':
            rng_mode = "3digit_last"
            print("\n[✓] Mode: Random 3 digit terakhir (seluruh oktet ke-4)")
        else:
            print("[!] Pilihan tidak valid!")
            return
        
        base_ip = input("Masukkan IP lengkap (contoh: 157.7.44.176): ").strip()
        
        # Validasi IP
        parts = base_ip.split('.')
        if len(parts) != 4:
            print("[!] Format IP tidak valid! Harus 4 oktet.")
            return
        
        # Tanya jumlah IP valid yang diinginkan
        try:
            max_valid_input = input("\nJumlah IP valid yang ingin dicari (default 50): ").strip()
            if max_valid_input:
                max_valid_rng = int(max_valid_input)
            else:
                max_valid_rng = 50
        except:
            print("[*] Menggunakan default 50")
            max_valid_rng = 50
        
        # Tampilkan konfirmasi
        print(f"\n[✓] Base IP: {base_ip}")
        print(f"[✓] 3 oktet tetap: {'.'.join(parts[:3])}")
        print(f"[✓] Mode RNG: {rng_mode}")
        print(f"[✓] Target: {max_valid_rng} IP valid")
        
        scanner = MovableTypeScanner(proxy_list=proxies, max_threads=50, max_valid_rng=max_valid_rng)
        scanner.scan_random_ips_from_base(base_ip, rng_mode)
            
    else:
        print("[!] Pilihan tidak valid!")
        return
    
    print("\n[*] Scan selesai!")
    print(f"[*] Hasil disimpan di:")
    print(f"    - {scanner.output_files['movable_type']} (URL mt-xmlrpc.cgi dari rsd.xml dengan status 403/411/405)")
    print(f"    - {scanner.output_files['movable_type_v4']} (URL mt-upgrade.cgi untuk versi 4 dengan status 200)")

if __name__ == "__main__":
    main()
