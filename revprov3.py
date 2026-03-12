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
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import urllib3

# Nonaktifkan SSL warnings untuk mengurangi noise
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class MovableTypeScanner:
    def __init__(self, proxy_list=None, max_threads=30, max_valid_rng=50):
        self.ua = UserAgent()
        self.max_threads = max_threads
        self.max_valid_rng = max_valid_rng
        self.proxy_list = proxy_list or []
        self.current_proxy_index = 0
        self.lock = threading.Lock()
        self.found_urls = set()  # Untuk mencegah duplikat
        self.proxy_fail_count = {}  # Counter untuk proxy yang gagal
        
        # Headers untuk requests
        self.headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate",
            "DNT": "1",
            "Connection": "close"  # PENTING: close connection setelah setiap request
        }
        
        # File output
        self.output_files = {
            'movable_type': 'movable_type.txt',
            'movable_type_v4': 'movable_type_v4.txt'
        }
        
        # Buat file output kosong
        for file in self.output_files.values():
            open(file, 'w').close()
    
    def create_session(self):
        """Membuat session baru dengan konfigurasi optimal"""
        session = requests.Session()
        
        # Konfigurasi retry strategy
        retry_strategy = Retry(
            total=1,  # Cuma 1 kali retry
            backoff_factor=0.1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        
        # Mount adapter dengan koneksi terbatas
        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=10,  # Batasi pool koneksi
            pool_maxsize=10,
            pool_block=True
        )
        
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        return session
    
    def get_proxy(self):
        """Mendapatkan proxy secara bergantian dengan pengecekan kesehatan"""
        if not self.proxy_list:
            return None
            
        with self.lock:
            # Cari proxy yang belum terlalu banyak gagal
            for _ in range(len(self.proxy_list)):
                proxy = self.proxy_list[self.current_proxy_index]
                self.current_proxy_index = (self.current_proxy_index + 1) % len(self.proxy_list)
                
                # Lewati proxy yang terlalu sering gagal
                fail_count = self.proxy_fail_count.get(proxy, 0)
                if fail_count < 3:  # Maksimal 3 kali gagal
                    return {"http": proxy, "https": proxy}
            
            # Jika semua proxy gagal, return proxy pertama
            proxy = self.proxy_list[0]
            return {"http": proxy, "https": proxy}
    
    def mark_proxy_failed(self, proxy):
        """Tandai proxy yang gagal"""
        if proxy:
            proxy_str = proxy.get('http') if isinstance(proxy, dict) else str(proxy)
            with self.lock:
                self.proxy_fail_count[proxy_str] = self.proxy_fail_count.get(proxy_str, 0) + 1
                
                # Reset jika terlalu tinggi
                if self.proxy_fail_count[proxy_str] > 10:
                    self.proxy_fail_count[proxy_str] = 5
    
    def reverse_ip_tntcode(self, ip):
        """Reverse IP menggunakan tntcode.com dengan manajemen koneksi lebih baik"""
        # Buat session baru untuk setiap request
        session = self.create_session()
        
        try:
            url = f"https://domains.tntcode.com/ip/{ip}"
            headers = self.headers.copy()
            headers["User-Agent"] = self.ua.random
            
            proxies = self.get_proxy()
            
            # Gunakan timeout lebih agresif
            response = session.get(
                url, 
                headers=headers, 
                proxies=proxies, 
                timeout=(8, 15),  # (connect timeout, read timeout)
                verify=False,  # Abaikan SSL verification untuk kecepatan
                allow_redirects=True
            )
            
            domains = re.findall(r'<a href="/domain/(.+?)"', response.text)
            return domains
            
        except requests.exceptions.ConnectTimeout:
            print(f"  [-][TNT] Connection timeout")
            self.mark_proxy_failed(proxies)
            return []
        except requests.exceptions.ReadTimeout:
            print(f"  [-][TNT] Read timeout")
            self.mark_proxy_failed(proxies)
            return []
        except requests.exceptions.ProxyError:
            print(f"  [-][TNT] Proxy error")
            self.mark_proxy_failed(proxies)
            return []
        except requests.exceptions.SSLError:
            # Coba tanpa SSL
            try:
                url = f"http://domains.tntcode.com/ip/{ip}"  # Coba HTTP
                response = session.get(
                    url, headers=headers, proxies=proxies, 
                    timeout=(8, 15), verify=False
                )
                domains = re.findall(r'<a href="/domain/(.+?)"', response.text)
                return domains
            except:
                return []
        except Exception as e:
            print(f"  [-][TNT] Error: {str(e)[:30]}")
            self.mark_proxy_failed(proxies)
            return []
        finally:
            # PENTING: Tutup session
            session.close()
    
    def reverse_ip_hackertarget(self, ip):
        """Reverse IP menggunakan hackertarget.com dengan manajemen koneksi lebih baik"""
        # Buat session baru untuk setiap request
        session = self.create_session()
        
        try:
            url = f"https://api.hackertarget.com/reverseiplookup/?q={ip}"
            headers = self.headers.copy()
            headers["User-Agent"] = self.ua.random
            
            proxies = self.get_proxy()
            
            # Gunakan timeout lebih agresif
            response = session.get(
                url, 
                headers=headers, 
                proxies=proxies, 
                timeout=(6, 12),  # Timeout lebih pendek untuk API
                verify=False,
                allow_redirects=False
            )
            
            if response.text and "error" not in response.text.lower():
                # Filter domain yang valid
                domains = [line.strip() for line in response.text.strip().split('\n') if line.strip()]
                return domains
            return []
            
        except requests.exceptions.ConnectTimeout:
            print(f"  [-][HT] Connection timeout")
            self.mark_proxy_failed(proxies)
            return []
        except requests.exceptions.ReadTimeout:
            print(f"  [-][HT] Read timeout")
            self.mark_proxy_failed(proxies)
            return []
        except requests.exceptions.ProxyError:
            print(f"  [-][HT] Proxy error")
            self.mark_proxy_failed(proxies)
            return []
        except Exception as e:
            print(f"  [-][HT] Error: {str(e)[:30]}")
            self.mark_proxy_failed(proxies)
            return []
        finally:
            # PENTING: Tutup session
            session.close()
    
    def check_ip_valid(self, ip):
        """Memeriksa apakah IP valid dengan timeout singkat"""
        try:
            socket.setdefaulttimeout(2)  # Timeout 2 detik
            socket.gethostbyaddr(ip)
            return True
        except:
            return False
        finally:
            socket.setdefaulttimeout(None)  # Reset timeout
    
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
                print(f"  [+] IP Valid: {ip} ({len(valid_ips)}/{max_valid})")
        
        print(f"[*] Total {len(valid_ips)} IP valid ditemukan")
        return valid_ips
    
    def check_rsd_xml(self, domain):
        """Memeriksa keberadaan rsd.xml dengan connection handling lebih baik"""
        paths = ['/rsd.xml', '/blog/rsd.xml']
        
        # Buat session baru
        session = self.create_session()
        
        try:
            for path in paths:
                for protocol in ['http', 'https']:
                    try:
                        url = f"{protocol}://{domain}{path}"
                        headers = self.headers.copy()
                        headers["User-Agent"] = self.ua.random
                        
                        # TANPA PROXY - langsung koneksi dengan timeout ketat
                        response = session.get(
                            url, 
                            headers=headers, 
                            timeout=5,  # Timeout 5 detik
                            verify=False,
                            allow_redirects=False
                        )
                        
                        if response.status_code == 200 and 'rsd' in response.text.lower():
                            return response.text, url
                    except:
                        continue
        finally:
            session.close()
            
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
                session = self.create_session()
                try:
                    headers = self.headers.copy()
                    headers["User-Agent"] = self.ua.random
                    
                    response = session.get(
                        xmlrpc_url, 
                        headers=headers, 
                        timeout=8, 
                        allow_redirects=False,
                        verify=False
                    )
                    
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
                        print(f"    [+] Movable Type: {display_url} (Status: {response.status_code})")
                        
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
                                upgrade_response = session.get(
                                    upgrade_url, 
                                    headers=headers, 
                                    timeout=8, 
                                    allow_redirects=False,
                                    verify=False
                                )
                                if upgrade_response.status_code == 200:
                                    upgrade_key = f"{upgrade_url}|200"
                                    if upgrade_key not in self.found_urls:
                                        self.found_urls.add(upgrade_key)
                                        
                                        # Simpan ke file movable_type_v4.txt
                                        with open(self.output_files['movable_type_v4'], 'a') as f:
                                            f.write(f"{upgrade_url}\n")
                                        
                                        display_upgrade = upgrade_url.replace('http://', '').replace('https://', '')
                                        print(f"    [!] MT v4 upgrade.cgi: {display_upgrade}")
                            except:
                                pass
                    
                except Exception as e:
                    continue
                finally:
                    session.close()
        
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
        
        # REVERSE IP - MENGGUNAKAN PROXY DENGAN MANAJEMEN KONEKSI BAIK
        print("  [*] Reverse IP dengan proxy...")
        
        # Gunakan threading untuk kedua source sekaligus
        domains_tnt = []
        domains_ht = []
        
        def get_tnt():
            nonlocal domains_tnt
            domains_tnt = self.reverse_ip_tntcode(ip)
        
        def get_ht():
            nonlocal domains_ht
            domains_ht = self.reverse_ip_hackertarget(ip)
        
        # Jalankan kedua reverse IP secara paralel
        t1 = threading.Thread(target=get_tnt)
        t2 = threading.Thread(target=get_ht)
        
        t1.start()
        t2.start()
        
        t1.join(timeout=20)  # Timeout 20 detik
        t2.join(timeout=20)
        
        print(f"  [+] TNTCode: {len(domains_tnt)} domain")
        print(f"  [+] HackerTarget: {len(domains_ht)} domain")
        
        # Gabungkan dan hapus duplikat
        all_domains = list(set(domains_tnt + domains_ht))
        
        if all_domains:
            print(f"  [+] Total domain unik: {len(all_domains)}")
            
            # SCAN DOMAIN - TANPA PROXY
            print("  [*] Scanning domain...")
            found_count = 0
            
            # Batch process untuk menghindari terlalu banyak koneksi sekaligus
            batch_size = 15
            for i in range(0, len(all_domains), batch_size):
                batch = all_domains[i:i+batch_size]
                
                with ThreadPoolExecutor(max_workers=10) as executor:
                    futures = [executor.submit(self.scan_domain, domain) for domain in batch]
                    for future in as_completed(futures):
                        try:
                            results = future.result(timeout=10)
                            if results:
                                found_count += len(results)
                        except:
                            pass
                
                # Jeda antar batch
                time.sleep(0.3)
            
            print(f"  [+] Selesai: {found_count} MT ditemukan")
        else:
            print(f"  [-] Tidak ada domain ditemukan")
    
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
        response = requests.get(proxy_url, headers=headers, timeout=20)
        
        if response.status_code == 200:
            # Ambil semua proxy (format sudah sesuai: protocol://ip:port)
            proxies = [line.strip() for line in response.text.split('\n') if line.strip()]
            
            # Filter hanya proxy yang valid (minimal ada protocol://)
            valid_proxies = [p for p in proxies if '://' in p]
            
            print(f"[+] Berhasil mendapatkan {len(valid_proxies)} proxy")
            
            # Ambil 50 proxy pertama saja untuk menghindari overload
            if len(valid_proxies) > 50:
                valid_proxies = valid_proxies[:50]
                print(f"[+] Menggunakan 50 proxy terbaik")
            
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
    ║     Movable Type Mass Scanner v2.0       ║
    ║   Optimized - No More Connection Pool    ║
    ║         Connection Issues Fixed           ║
    ╚══════════════════════════════════════════╝
    """)
    
    # Langsung ambil proxy online, tanpa tanya, tanpa file
    proxies = get_proxies()
    
    # Setup scanner dengan thread lebih sedikit untuk stabilitas
    max_valid_rng = 50
    
    print("\nPilih metode input:")
    print("1. Scan dari file list IP")
    print("2. Scan dengan RNG IP (2 digit terakhir random)")
    
    choice = input("\nPilihan (1/2): ").strip()
    
    if choice == '1':
        filename = input("Masukkan nama file list IP: ").strip()
        if filename:
            scanner = MovableTypeScanner(
                proxy_list=proxies, 
                max_threads=20,  # Kurangi thread untuk stabilitas
                max_valid_rng=max_valid_rng
            )
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
            
            scanner = MovableTypeScanner(
                proxy_list=proxies, 
                max_threads=15,  # Kurangi thread untuk RNG
                max_valid_rng=max_valid_rng
            )
            scanner.scan_random_ips(base_ip)
            
    else:
        print("[!] Pilihan tidak valid!")
        return
    
    print("\n" + "="*50)
    print("[*] SCAN SELESAI!")
    print("[*] Hasil disimpan di:")
    print(f"    - {scanner.output_files['movable_type']} (URL mt-xmlrpc.cgi dari rsd.xml dengan status 403/411/405)")
    print(f"    - {scanner.output_files['movable_type_v4']} (URL mt-upgrade.cgi untuk versi 4 dengan status 200)")
    print("="*50)

if __name__ == "__main__":
    main()
