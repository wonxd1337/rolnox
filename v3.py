import requests
import re
import time
import random
import threading
import signal
import sys
import gc
from queue import Queue
from fake_useragent import UserAgent
from urllib.parse import urlparse
import socket
import psutil
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from requests.packages.urllib3.exceptions import InsecureRequestWarning
from collections import OrderedDict

# Nonaktifkan peringatan SSL
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

class MovableTypeScanner:
    def __init__(self, proxy_list=None, max_threads=50, max_valid_rng=50):
        self.ua = UserAgent()
        self.max_threads = max_threads
        self.max_valid_rng = max_valid_rng
        
        # Buat session baru dengan connection pooling terbatas
        self.session = self._create_session()
        
        self.proxy_list = proxy_list or []
        self.current_proxy_index = 0
        self.lock = threading.Lock()
        
        # === OPTIMASI MEMORY: Gunakan LRU Cache ===
        self.found_urls = OrderedDict()  # Ganti set dengan OrderedDict
        self.max_cache_size = 10000  # Batasi cache
        
        # Weighted proxy dengan ukuran tetap
        self.proxy_stats = {}
        self.proxy_weights = {}
        self.min_weight = 0.1
        self.max_weight = 3.0
        
        # === ANTI KILL: Graceful Shutdown ===
        self.running = True
        self.current_futures = []
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        
        # Headers
        self.headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate",
            "DNT": "1",
            "Connection": "close"  # Force close connection
        }
        
        # File output
        self.output_files = {
            'movable_type': 'movable_type.txt',
            'movable_type_v4': 'movable_type_v4.txt'
        }
        
        # Inisialisasi proxy stats
        for proxy in self.proxy_list[:500]:  # Batasi jumlah proxy
            self.proxy_stats[proxy] = {
                'success': 0,
                'fail': 0,
                'total_time': 0,
                'avg_time': 1.0,
                'weight': 1.0
            }
            self.proxy_weights[proxy] = 1.0
        
        # === MONITORING ===
        self.stats = {
            'ips_processed': 0,
            'domains_found': 0,
            'errors': 0,
            'start_time': time.time()
        }
    
    def _create_session(self):
        """Buat session dengan konfigurasi optimal"""
        session = requests.Session()
        
        # Batasi connection pool
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=10,  # Maks koneksi simultan
            pool_maxsize=20,       # Maks pool size
            max_retries=2,         # Retry terbatas
            pool_block=True        # Block jika pool penuh
        )
        session.mount('http://', adapter)
        session.mount('https://', adapter)
        
        # Timeouts
        session.timeout = (5, 10)  # connect, read timeout
        
        return session
    
    def signal_handler(self, signum, frame):
        """Handle Ctrl+C dan termination signal"""
        print("\n\n[!] Menerima sinyal termination. Menyimpan progress...")
        self.running = False
        
        # Cancel semua future yang pending
        for future in self.current_futures:
            future.cancel()
        
        print("[*] Menunggu thread selesai (max 5 detik)...")
        time.sleep(5)
        
        print("[*] Progress tersimpan. Exiting...")
        sys.exit(0)
    
    def clean_cache(self):
        """Bersihkan cache jika terlalu besar"""
        with self.lock:
            if len(self.found_urls) > self.max_cache_size:
                # Hapus 20% tertua
                items_to_remove = int(self.max_cache_size * 0.2)
                for _ in range(items_to_remove):
                    self.found_urls.popitem(last=False)
                print(f"[GC] Cache dibersihkan: {items_to_remove} item dihapus")
            
            # Panggil garbage collector manual
            gc.collect()
    
    def check_memory_usage(self):
        """Monitor memory usage"""
        process = psutil.Process(os.getpid())
        memory_usage = process.memory_info().rss / 1024 / 1024  # MB
        
        if memory_usage > 500:  # Jika > 500MB
            print(f"[!] Memory usage tinggi: {memory_usage:.2f}MB. Membersihkan...")
            gc.collect()
            
            # Reset session untuk free connections
            self.session.close()
            self.session = self._create_session()
            
            return False
        return True
    
    def add_to_cache(self, key):
        """Add ke cache dengan LRU logic"""
        with self.lock:
            self.found_urls[key] = time.time()
            self.found_urls.move_to_end(key)
            self.clean_cache()
    
    def is_cached(self, key):
        """Cek cache"""
        with self.lock:
            return key in self.found_urls
    
    def update_proxy_stats(self, proxy, success, response_time=None):
        """Update statistik dengan batasan"""
        if not proxy or proxy not in self.proxy_stats:
            return
        
        with self.lock:
            stats = self.proxy_stats[proxy]
            
            if success and response_time:
                stats['success'] += 1
                stats['total_time'] += response_time
                total = stats['success'] + stats['fail']
                stats['avg_time'] = stats['total_time'] / total if total > 0 else response_time
            else:
                stats['fail'] += 1
            
            # Hitung ulang bobot
            total = stats['success'] + stats['fail']
            if total > 10:  # Hanya hitung setelah cukup data
                success_rate = stats['success'] / total
                speed_score = 1.0 / stats['avg_time'] if stats['avg_time'] > 0 else 1.0
                speed_score = min(speed_score, 2.0)
                
                weight = (success_rate * 0.6 + speed_score * 0.4) * 2
                stats['weight'] = max(self.min_weight, min(self.max_weight, weight))
                self.proxy_weights[proxy] = stats['weight']
    
    def get_weighted_proxy(self):
        """Get proxy dengan timeout dan fallback"""
        if not self.proxy_list or not self.running:
            return None
        
        try:
            with self.lock:
                # Filter proxy yang masih aktif
                active_proxies = [p for p in self.proxy_weights 
                                 if p in self.proxy_stats and 
                                 self.proxy_stats[p]['fail'] < 10]  # Abaikan proxy yang gagal >10x
                
                if not active_proxies:
                    return None
                
                total_weight = sum(self.proxy_weights[p] for p in active_proxies)
                
                if total_weight <= 0:
                    return {"http": random.choice(active_proxies), 
                           "https": random.choice(active_proxies)}
                
                r = random.uniform(0, total_weight)
                cumulative = 0
                
                for proxy in active_proxies:
                    cumulative += self.proxy_weights[proxy]
                    if r <= cumulative:
                        return {"http": proxy, "https": proxy}
                
                # Fallback
                proxy = random.choice(active_proxies)
                return {"http": proxy, "https": proxy}
                
        except Exception:
            return None
    
    def reverse_ip_tntcode(self, ip):
        """Reverse IP dengan error handling lebih baik"""
        if not self.running:
            return []
        
        proxy_used = None
        start_time = time.time()
        
        try:
            url = f"https://domains.tntcode.com/ip/{ip}"
            headers = self.headers.copy()
            headers["User-Agent"] = self.ua.random
            
            proxies = self.get_weighted_proxy()
            if proxies:
                proxy_used = list(proxies.values())[0]
            
            # Dengan timeout ketat
            response = self.session.get(
                url, 
                headers=headers, 
                proxies=proxies, 
                timeout=(5, 15),  # connect=5s, read=15s
                verify=False
            )
            
            response_time = time.time() - start_time
            
            if proxy_used:
                self.update_proxy_stats(proxy_used, True, response_time)
            
            domains = re.findall(r'<a href="/domain/(.+?)"', response.text)
            return domains[:100]  # Batasi hasil
            
        except requests.exceptions.Timeout:
            if proxy_used:
                self.update_proxy_stats(proxy_used, False)
            return []
        except Exception as e:
            if proxy_used:
                self.update_proxy_stats(proxy_used, False)
            return []
    
    def reverse_ip_hackertarget(self, ip):
        """Sama seperti di atas dengan timeout ketat"""
        if not self.running:
            return []
        
        proxy_used = None
        start_time = time.time()
        
        try:
            url = f"https://api.hackertarget.com/reverseiplookup/?q={ip}"
            headers = self.headers.copy()
            headers["User-Agent"] = self.ua.random
            
            proxies = self.get_weighted_proxy()
            if proxies:
                proxy_used = list(proxies.values())[0]
            
            response = self.session.get(
                url, 
                headers=headers, 
                proxies=proxies, 
                timeout=(5, 15),
                verify=False
            )
            
            response_time = time.time() - start_time
            
            if proxy_used:
                self.update_proxy_stats(proxy_used, True, response_time)
            
            if response.text and "error" not in response.text.lower():
                domains = response.text.strip().split('\n')
                return domains[:100]  # Batasi
            
            return []
            
        except Exception:
            if proxy_used:
                self.update_proxy_stats(proxy_used, False)
            return []
    
    def process_ip(self, ip):
        """Process IP dengan monitoring"""
        if not self.running:
            return
        
        # Cek memory
        if not self.check_memory_usage():
            time.sleep(2)  # Kasih waktu GC bekerja
        
        with self.lock:
            self.stats['ips_processed'] += 1
        
        print(f"\n[*] Memproses IP: {ip} ({self.stats['ips_processed']} processed)")
        
        # Tampilkan stats setiap 10 IP
        if self.stats['ips_processed'] % 10 == 0:
            elapsed = time.time() - self.stats['start_time']
            print(f"\n[STATS] {self.stats['ips_processed']} IP dalam {elapsed:.0f}s")
            print(f"[STATS] Domain ditemukan: {self.stats['domains_found']}")
            print(f"[STATS] Errors: {self.stats['errors']}")
        
        # Reverse IP
        domains_tnt = self.reverse_ip_tntcode(ip)
        domains_ht = self.reverse_ip_hackertarget(ip)
        
        all_domains = list(set(domains_tnt + domains_ht))
        
        if all_domains:
            print(f"[+] Total domain: {len(all_domains)}")
            
            # Scan dengan batch processing
            found_count = 0
            batch_size = 20
            
            for i in range(0, len(all_domains), batch_size):
                if not self.running:
                    break
                    
                batch = all_domains[i:i+batch_size]
                
                with ThreadPoolExecutor(max_workers=20) as executor:
                    futures = [executor.submit(self.scan_domain, domain) for domain in batch]
                    self.current_futures = futures
                    
                    for future in as_completed(futures):
                        if not self.running:
                            future.cancel()
                            break
                        try:
                            results = future.result(timeout=10)
                            if results:
                                found_count += len(results)
                                with self.lock:
                                    self.stats['domains_found'] += len(results)
                        except Exception:
                            with self.lock:
                                self.stats['errors'] += 1
                            continue
                    
                    self.current_futures = []
            
            print(f"[+] IP {ip}: {found_count} ditemukan")
        else:
            print(f"[-] Tidak ada domain")
    
    def scan_domain(self, domain):
        """Scan domain dengan timeout"""
        if not self.running:
            return []
        
        try:
            rsd_content, rsd_url = self.check_rsd_xml(domain)
            
            if rsd_content:
                mt_info = self.extract_mt_info(rsd_content)
                
                if mt_info['engine'] and 'movable type' in mt_info['engine'].lower():
                    results = self.check_mt_endpoints(domain, mt_info)
                    return results
        except Exception:
            pass
        return []
    
    def check_rsd_xml(self, domain):
        """Cek rsd.xml dengan timeout ketat"""
        paths = ['/rsd.xml', '/blog/rsd.xml']
        
        for path in paths:
            for protocol in ['http', 'https']:
                try:
                    url = f"{protocol}://{domain}{path}"
                    headers = self.headers.copy()
                    headers["User-Agent"] = self.ua.random
                    
                    response = self.session.get(
                        url, 
                        headers=headers, 
                        timeout=5,  # Timeout singkat
                        verify=False,
                        allow_redirects=False
                    )
                    
                    if response.status_code == 200 and 'rsd' in response.text.lower():
                        return response.text, url
                except:
                    continue
        return None, None
    
    def scan_from_file(self, filename):
        """Scan dari file dengan resume capability"""
        try:
            with open(filename, 'r') as f:
                all_ips = [line.strip() for line in f if line.strip()]
            
            # Cek file progress
            processed_file = 'processed_ips.txt'
            processed = set()
            if os.path.exists(processed_file):
                with open(processed_file, 'r') as pf:
                    processed = set([line.strip() for line in pf])
            
            ips = [ip for ip in all_ips if ip not in processed]
            print(f"[*] Total: {len(all_ips)}, Sisa: {len(ips)}")
            
            for i, ip in enumerate(ips):
                if not self.running:
                    break
                
                self.process_ip(ip)
                
                # Simpan progress
                with open(processed_file, 'a') as pf:
                    pf.write(f"{ip}\n")
                
                # Delay antar IP
                time.sleep(1)
                
        except Exception as e:
            print(f"[!] Error: {e}")
    
    def print_final_stats(self):
        """Tampilkan statistik final"""
        elapsed = time.time() - self.stats['start_time']
        print("\n" + "="*50)
        print("STATISTIK FINAL")
        print("="*50)
        print(f"Total waktu: {elapsed:.0f} detik")
        print(f"IP diproses: {self.stats['ips_processed']}")
        print(f"Domain ditemukan: {self.stats['domains_found']}")
        print(f"Total errors: {self.stats['errors']}")
        print(f"Kecepatan: {self.stats['ips_processed']/elapsed*60:.1f} IP/menit")


# [Download proxy function tetap sama]
def download_proxy_list():
    # ... (sama seperti sebelumnya)

def get_proxies():
    # ... (sama seperti sebelumnya)

def main():
    print("""
    ╔══════════════════════════════════════════════════════╗
    ║     Movable Type Mass Scanner v2.0                   ║
    ║   - Anti-Kill & Anti-Memory Leak                     ║
    ║   - Resume Capability                                ║
    ║   - Graceful Shutdown                                ║
    ║   - Memory Monitoring                                ║
    ╚══════════════════════════════════════════════════════╝
    """)
    
    proxies = get_proxies()
    scanner = MovableTypeScanner(proxy_list=proxies, max_threads=30)  # Kurangi thread
    
    try:
        choice = input("\nPilihan (1/2): ").strip()
        
        if choice == '1':
            filename = input("File list IP: ").strip()
            scanner.scan_from_file(filename)
        elif choice == '2':
            base_ip = input("Base IP: ").strip()
            scanner.scan_random_ips(base_ip)
        
        scanner.print_final_stats()
        
    except KeyboardInterrupt:
        print("\n\n[!] Dihentikan user. Progress tersimpan.")
        scanner.print_final_stats()

if __name__ == "__main__":
    main()
