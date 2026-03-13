import requests
import re
import time
import random
import threading
from queue import Queue, PriorityQueue
from fake_useragent import UserAgent
from urllib.parse import urlparse
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

class ProxyManager:
    def __init__(self, proxy_list):
        self.proxy_pool = []  # List of proxy dengan rating
        self.lock = threading.Lock()
        self.current_index = 0
        self.blacklist = set()  # Proxy yang gagal total
        self.stats = {
            'total_used': 0,
            'failed': 0,
            'success': 0,
            'total_requests': 0
        }
        
        # Inisialisasi proxy pool
        for proxy in proxy_list:
            self.proxy_pool.append({
                'proxy': proxy,
                'rating': 100,  # Rating awal 100
                'fail_count': 0,
                'success_count': 0,
                'last_check': None,
                'avg_response': 0,
                'total_requests': 0
            })
        
        print(f"[*] ProxyManager initialized with {len(self.proxy_pool)} proxies")
    
    def test_proxy(self, proxy_dict, timeout=5):
        """Test single proxy"""
        try:
            proxy = proxy_dict['proxy']
            proxies = {"http": proxy, "https": proxy}
            
            # Test ke beberapa endpoint untuk akurasi
            test_urls = [
                "http://httpbin.org/ip",
                "https://api.ipify.org",
                "http://ip-api.com/json"
            ]
            
            start_time = time.time()
            
            for url in test_urls[:2]:  # Coba 2 endpoint
                try:
                    response = requests.get(url, proxies=proxies, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
                    if response.status_code == 200:
                        proxy_dict['avg_response'] = time.time() - start_time
                        proxy_dict['last_check'] = datetime.now()
                        return True
                except:
                    continue
            
            return False
        except:
            return False
    
    def check_all_proxies(self, max_workers=20):
        """Check semua proxy secara parallel"""
        print(f"[*] Memeriksa {len(self.proxy_pool)} proxy...")
        
        active_proxies = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(self.test_proxy, proxy): proxy 
                      for proxy in self.proxy_pool}
            
            for future in as_completed(futures):
                proxy_dict = futures[future]
                try:
                    if future.result():
                        active_proxies.append(proxy_dict)
                        print(f"[+] Proxy aktif: {proxy_dict['proxy']} ({proxy_dict['avg_response']:.2f}s)")
                    else:
                        print(f"[-] Proxy mati: {proxy_dict['proxy']}")
                        self.blacklist.add(proxy_dict['proxy'])
                except:
                    pass
        
        # Urutkan berdasarkan response time (yang tercepat)
        active_proxies.sort(key=lambda x: x['avg_response'])
        
        print(f"[+] Total proxy aktif: {len(active_proxies)}/{len(self.proxy_pool)}")
        self.proxy_pool = active_proxies
        
        # Hitung statistik
        if active_proxies:
            avg_response = sum(p['avg_response'] for p in active_proxies) / len(active_proxies)
            print(f"[+] Rata-rata response time: {avg_response:.2f}s")
        
        return active_proxies
    
    def get_next_proxy(self):
        """Round-robin dengan rating (hanya proxy dengan rating > 50)"""
        with self.lock:
            if not self.proxy_pool:
                return None
            
            # Filter proxy dengan rating > 50 (yang masih bagus)
            good_proxies = [p for p in self.proxy_pool if p['rating'] > 50]
            
            if not good_proxies:
                # Jika semua rating rendah, reset rating untuk kesempatan kedua
                print("[!] Semua proxy rating rendah, reset rating...")
                for p in self.proxy_pool:
                    p['rating'] = 60
                    p['fail_count'] = 0
                good_proxies = self.proxy_pool
            
            # Increment index dengan round-robin
            proxy_dict = good_proxies[self.current_index % len(good_proxies)]
            self.current_index += 1
            
            return proxy_dict
    
    def report_success(self, proxy_dict):
        """Laporkan proxy berhasil"""
        with self.lock:
            proxy_dict['success_count'] += 1
            proxy_dict['total_requests'] += 1
            proxy_dict['rating'] = min(100, proxy_dict['rating'] + 5)
            proxy_dict['fail_count'] = max(0, proxy_dict['fail_count'] - 1)
            self.stats['success'] += 1
            self.stats['total_requests'] += 1
    
    def report_failure(self, proxy_dict):
        """Laporkan proxy gagal"""
        with self.lock:
            proxy_dict['fail_count'] += 1
            proxy_dict['total_requests'] += 1
            proxy_dict['rating'] = max(0, proxy_dict['rating'] - 15)
            self.stats['failed'] += 1
            self.stats['total_requests'] += 1
            
            # Jika terlalu banyak gagal, blacklist
            if proxy_dict['fail_count'] >= 3:
                if proxy_dict in self.proxy_pool:
                    self.proxy_pool.remove(proxy_dict)
                    self.blacklist.add(proxy_dict['proxy'])
                    print(f"[!] Proxy {proxy_dict['proxy']} di-blacklist (3x gagal berturut-turut)")
    
    def get_proxy_for_request(self, ip, service_name):
        """Dapatkan proxy untuk request dengan retry otomatis"""
        max_attempts = len(self.proxy_pool) * 2  # Maksimal attempt
        
        for attempt in range(max_attempts):
            proxy_dict = self.get_next_proxy()
            
            if not proxy_dict:
                print(f"[!] TIDAK ADA PROXY TERSEDIA untuk {service_name} {ip} - SKIP IP")
                return None
            
            print(f"[*] {service_name} {ip} - Attempt {attempt+1} dengan proxy {proxy_dict['proxy']} (Rating: {proxy_dict['rating']})")
            
            # Test cepat proxy sebelum digunakan (timeout singkat)
            if self.quick_test_proxy(proxy_dict['proxy']):
                return proxy_dict
            else:
                self.report_failure(proxy_dict)
        
        print(f"[!] SEMUA PERCOBAAN PROXY GAGAL untuk {service_name} {ip} - SKIP IP")
        return None
    
    def quick_test_proxy(self, proxy):
        """Test cepat proxy sebelum digunakan"""
        try:
            proxies = {"http": proxy, "https": proxy}
            response = requests.get("http://httpbin.org/ip", 
                                  proxies=proxies, 
                                  timeout=3,
                                  headers={"User-Agent": "Mozilla/5.0"})
            return response.status_code == 200
        except:
            return False
    
    def get_stats(self):
        """Dapatkan statistik proxy"""
        if not self.proxy_pool:
            return {
                'total_active': 0,
                'blacklisted': len(self.blacklist),
                'success_rate': 0,
                'avg_rating': 0,
                'total_requests': self.stats['total_requests']
            }
        
        return {
            'total_active': len(self.proxy_pool),
            'blacklisted': len(self.blacklist),
            'success_rate': (self.stats['success'] / max(1, self.stats['total_requests'])) * 100,
            'avg_rating': sum(p['rating'] for p in self.proxy_pool) / len(self.proxy_pool),
            'total_requests': self.stats['total_requests']
        }


class MovableTypeScanner:
    def __init__(self, proxy_list=None, max_threads=50, max_valid_rng=50):
        self.ua = UserAgent()
        self.max_threads = max_threads
        self.max_valid_rng = max_valid_rng
        self.session = requests.Session()
        
        # Gunakan ProxyManager
        if proxy_list:
            self.proxy_manager = ProxyManager(proxy_list)
            # Check semua proxy di awal
            self.proxy_manager.check_all_proxies()
        else:
            self.proxy_manager = None
            print("[!] TIDAK ADA PROXY - Scan akan menggunakan koneksi langsung (TIDAK DIREKOMENDASIKAN)")
        
        self.found_urls = set()  # Untuk mencegah duplikat
        self.stats = {
            'ips_processed': 0,
            'ips_skipped_no_proxy': 0,
            'domains_found': 0,
            'movable_type_found': 0
        }
        
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
        
        # Buat file output baru
        for f in self.output_files.values():
            open(f, 'w').close()
    
    def reverse_ip_tntcode(self, ip):
        """Reverse IP menggunakan tntcode.com DENGAN PROXY WAJIB"""
        if not self.proxy_manager:
            print(f"[!] TIDAK ADA PROXY - Tidak bisa reverse IP {ip}")
            return None
        
        # Dapatkan proxy untuk request ini
        proxy_dict = self.proxy_manager.get_proxy_for_request(ip, "TNTCode")
        
        if not proxy_dict:
            print(f"[!] GAGAL MENDAPATKAN PROXY untuk TNTCode {ip} - SKIP")
            return None
        
        try:
            url = f"https://domains.tntcode.com/ip/{ip}"
            headers = self.headers.copy()
            headers["User-Agent"] = self.ua.random
            
            proxies = {"http": proxy_dict['proxy'], "https": proxy_dict['proxy']}
            response = self.session.get(url, headers=headers, proxies=proxies, timeout=30)
            
            if response.status_code == 200:
                domains = re.findall(r'<a href="/domain/(.+?)"', response.text)
                self.proxy_manager.report_success(proxy_dict)
                return domains
            else:
                self.proxy_manager.report_failure(proxy_dict)
                print(f"[-] TNTCode {ip} - Status code: {response.status_code}")
                return None
                
        except Exception as e:
            self.proxy_manager.report_failure(proxy_dict)
            print(f"[-] TNTCode error untuk {ip}: {str(e)[:50]}")
            return None
    
    def reverse_ip_hackertarget(self, ip):
        """Reverse IP menggunakan hackertarget.com DENGAN PROXY WAJIB"""
        if not self.proxy_manager:
            print(f"[!] TIDAK ADA PROXY - Tidak bisa reverse IP {ip}")
            return None
        
        # Dapatkan proxy untuk request ini
        proxy_dict = self.proxy_manager.get_proxy_for_request(ip, "HackerTarget")
        
        if not proxy_dict:
            print(f"[!] GAGAL MENDAPATKAN PROXY untuk HackerTarget {ip} - SKIP")
            return None
        
        try:
            url = f"https://api.hackertarget.com/reverseiplookup/?q={ip}"
            headers = self.headers.copy()
            headers["User-Agent"] = self.ua.random
            
            proxies = {"http": proxy_dict['proxy'], "https": proxy_dict['proxy']}
            response = self.session.get(url, headers=headers, proxies=proxies, timeout=30)
            
            if response.status_code == 200 and response.text and "error" not in response.text.lower():
                domains = response.text.strip().split('\n')
                # Filter domain yang valid
                domains = [d for d in domains if d and '.' in d]
                self.proxy_manager.report_success(proxy_dict)
                return domains
            else:
                self.proxy_manager.report_failure(proxy_dict)
                return None
                
        except Exception as e:
            self.proxy_manager.report_failure(proxy_dict)
            print(f"[-] HackerTarget error untuk {ip}: {str(e)[:50]}")
            return None
    
    def check_rsd_xml(self, domain):
        """Memeriksa keberadaan rsd.xml (TANPA PROXY untuk kecepatan)"""
        paths = ['/rsd.xml', '/blog/rsd.xml', '/wordpress/rsd.xml', '/wp/rsd.xml']
        
        for path in paths:
            try:
                url = f"http://{domain}{path}"
                headers = self.headers.copy()
                headers["User-Agent"] = self.ua.random
                
                # TANPA PROXY - langsung koneksi
                response = self.session.get(url, headers=headers, timeout=5, allow_redirects=False)
                
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
                response = self.session.get(url, headers=headers, timeout=5, allow_redirects=False)
                
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
                    
                    response = self.session.get(xmlrpc_url, headers=headers, timeout=5, allow_redirects=False)
                    
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
                        
                        self.stats['movable_type_found'] += 1
                        
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
                                upgrade_response = self.session.get(upgrade_url, headers=headers, timeout=5, allow_redirects=False)
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
        """Proses satu IP untuk reverse IP (WAJIB PROXY) dan scan (tanpa proxy)"""
        self.stats['ips_processed'] += 1
        
        print(f"\n{'='*60}")
        print(f"[*] Memproses IP: {ip} (ke-{self.stats['ips_processed']})")
        
        # Cek apakah ada proxy tersedia
        if not self.proxy_manager or not self.proxy_manager.proxy_pool:
            print(f"[!] TIDAK ADA PROXY TERSEDIA - SKIP IP {ip}")
            self.stats['ips_skipped_no_proxy'] += 1
            return
        
        # Tampilkan statistik proxy
        proxy_stats = self.proxy_manager.get_stats()
        print(f"[*] Proxy Stats: Active={proxy_stats['total_active']}, Blacklisted={proxy_stats['blacklisted']}, Success Rate={proxy_stats['success_rate']:.1f}%")
        
        # REVERSE IP - WAJIB MENGGUNAKAN PROXY
        print("[*] Reverse IP dengan proxy...")
        
        domains_tnt = self.reverse_ip_tntcode(ip)
        if domains_tnt:
            print(f"[+] TNTCode: {len(domains_tnt)} domain ditemukan")
        else:
            print(f"[-] TNTCode: Gagal/Tidak ada domain")
        
        domains_ht = self.reverse_ip_hackertarget(ip)
        if domains_ht:
            print(f"[+] HackerTarget: {len(domains_ht)} domain ditemukan")
        else:
            print(f"[-] HackerTarget: Gagal/Tidak ada domain")
        
        # Gabungkan dan hapus duplikat
        all_domains = []
        if domains_tnt:
            all_domains.extend(domains_tnt)
        if domains_ht:
            all_domains.extend(domains_ht)
        
        all_domains = list(set(all_domains))
        
        if all_domains:
            print(f"[+] Total domain unik: {len(all_domains)}")
            self.stats['domains_found'] += len(all_domains)
            
            # SCAN DOMAIN - TANPA PROXY UNTUK KECEPATAN
            print("[*] Scanning domain tanpa proxy untuk kecepatan maksimal...")
            found_count = 0
            
            # Batch processing untuk menghindari overload
            batch_size = 20
            for i in range(0, len(all_domains), batch_size):
                batch = all_domains[i:i+batch_size]
                with ThreadPoolExecutor(max_workers=min(20, len(batch))) as executor:
                    futures = [executor.submit(self.scan_domain, domain) for domain in batch]
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
            
            print(f"\n[*] Memuat {len(ips)} IP dari file {filename}")
            
            # Filter IP valid
            valid_ips = []
            for ip in ips:
                parts = ip.split('.')
                if len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
                    valid_ips.append(ip)
            
            print(f"[*] IP valid: {len(valid_ips)}/{len(ips)}")
            
            start_time = time.time()
            
            with ThreadPoolExecutor(max_workers=self.max_threads) as executor:
                futures = [executor.submit(self.process_ip, ip) for ip in valid_ips]
                for future in as_completed(futures):
                    try:
                        future.result()
                        # Tampilkan progress setiap 10 IP
                        if self.stats['ips_processed'] % 10 == 0:
                            elapsed = time.time() - start_time
                            print(f"\n[PROGRESS] Processed: {self.stats['ips_processed']}/{len(valid_ips)} IP, Time: {elapsed:.0f}s")
                    except Exception as e:
                        print(f"[-] Error: {e}")
            
            # Tampilkan statistik akhir
            elapsed = time.time() - start_time
            print(f"\n{'='*60}")
            print("[*] SCAN SELESAI - STATISTIK:")
            print(f"    IP diproses: {self.stats['ips_processed']}")
            print(f"    IP skip (no proxy): {self.stats['ips_skipped_no_proxy']}")
            print(f"    Domain ditemukan: {self.stats['domains_found']}")
            print(f"    Movable Type: {self.stats['movable_type_found']}")
            print(f"    Waktu total: {elapsed:.0f} detik")
            
            if self.proxy_manager:
                proxy_stats = self.proxy_manager.get_stats()
                print(f"    Proxy aktif akhir: {proxy_stats['total_active']}")
                print(f"    Proxy blacklisted: {proxy_stats['blacklisted']}")
                print(f"    Success rate: {proxy_stats['success_rate']:.1f}%")
                        
        except Exception as e:
            print(f"[!] Error membaca file: {e}")
    
    def scan_random_ips(self, base_ip):
        """Scan dengan IP random dari base IP"""
        valid_ips = self.generate_random_ips(base_ip)
        
        if valid_ips:
            print(f"\n[*] Memulai scan untuk {len(valid_ips)} IP valid...")
            
            # Simpan ke file temp
            temp_file = "temp_random_ips.txt"
            with open(temp_file, 'w') as f:
                for ip in valid_ips:
                    f.write(f"{ip}\n")
            
            print(f"[*] IP random disimpan ke {temp_file}")
            
            # Scan menggunakan file
            self.scan_from_file(temp_file)
    
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
    
    def check_ip_valid(self, ip):
        """Memeriksa apakah IP valid dengan timeout singkat"""
        try:
            socket.gethostbyaddr(ip)
            return True
        except:
            return False


def download_proxy_list():
    """Download proxy list dari GitHub langsung ke memory"""
    proxy_url = "https://raw.githubusercontent.com/proxifly/free-proxy-list/refs/heads/main/proxies/protocols/http/data.txt"
    
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
            
            print(f"[+] Berhasil mendapatkan {len(valid_proxies)} proxy")
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
    
    # Jika tidak ada proxy online, return empty list
    print("[!] TIDAK ADA PROXY ONLINE - Scan tidak akan bisa melakukan reverse IP!")
    return []

def main():
    print("""\033[96m
    ╔══════════════════════════════════════════════════════════╗
    ║     Movable Type Mass Scanner v2.0 - PROXY MANAGER      ║
    ║         WAJIB PROXY untuk Reverse IP - NO FALLBACK      ║
    ║     Proxy Auto-Check & Rating System + Retry Mechanism  ║
    ╚══════════════════════════════════════════════════════════╝\033[0m
    """)
    
    # Langsung ambil proxy online
    proxies = get_proxies()
    
    if not proxies:
        print("\n\033[91m[!] TIDAK ADA PROXY TERSEDIA!\033[0m")
        print("[!] Script ini WAJIB menggunakan proxy untuk reverse IP")
        print("[!] Tanpa proxy, tidak akan ada domain yang ditemukan")
        
        choice = input("\nTetap lanjutkan? (y/n): ").strip().lower()
        if choice != 'y':
            print("[*] Exiting...")
            return
    
    # Setup scanner
    max_valid_rng = 50
    
    print("\nPilih metode input:")
    print("1. Scan dari file list IP")
    print("2. Scan dengan RNG IP (2 digit terakhir random)")
    
    choice = input("\nPilihan (1/2): ").strip()
    
    if choice == '1':
        filename = input("Masukkan nama file list IP: ").strip()
        if filename:
            scanner = MovableTypeScanner(proxy_list=proxies, max_threads=30, max_valid_rng=max_valid_rng)
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
            
            scanner = MovableTypeScanner(proxy_list=proxies, max_threads=30, max_valid_rng=max_valid_rng)
            scanner.scan_random_ips(base_ip)
            
    else:
        print("[!] Pilihan tidak valid!")
        return
    
    print("\n\033[92m[*] Scan selesai!\033[0m")
    print(f"[*] Hasil disimpan di:")
    print(f"    - movable_type.txt (URL mt-xmlrpc.cgi dari rsd.xml dengan status 403/411/405)")
    print(f"    - movable_type_v4.txt (URL mt-upgrade.cgi untuk versi 4 dengan status 200)")

if __name__ == "__main__":
    main()
