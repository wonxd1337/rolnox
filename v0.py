#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Movable Type Mass Scanner v2.0
Fitur:
- Anti-Kill & Anti-Memory Leak
- Weighted Proxy Selection
- SSL Verification Disabled
- Resume Capability
- Graceful Shutdown
- Memory Monitoring
- Auto Batch Processing
"""

import requests
import re
import time
import random
import threading
import signal
import sys
import gc
import os
import socket
from queue import Queue
from fake_useragent import UserAgent
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from requests.packages.urllib3.exceptions import InsecureRequestWarning
from collections import OrderedDict

# Nonaktifkan peringatan SSL
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)

# Cek ketersediaan psutil (optional)
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    print("[!] psutil tidak terinstall, memory monitoring terbatas")
    print("[!] Install dengan: pip install psutil")


class MovableTypeScanner:
    def __init__(self, proxy_list=None, max_threads=30, max_valid_rng=50):
        """
        Inisialisasi scanner dengan konfigurasi optimal
        """
        self.ua = UserAgent()
        self.max_threads = min(max_threads, 30)  # Batasi thread maksimal
        self.max_valid_rng = max_valid_rng
        
        # Buat session dengan konfigurasi optimal
        self.session = self._create_session()
        
        # Proxy configuration
        self.proxy_list = proxy_list or []
        self.current_proxy_index = 0
        self.lock = threading.Lock()
        
        # === ANTI MEMORY LEAK: LRU Cache ===
        self.found_urls = OrderedDict()
        self.max_cache_size = 5000  # Batasi cache
        self.found_domains = set()  # Untuk tracking domain
        
        # Weighted proxy dengan ukuran tetap
        self.proxy_stats = {}
        self.proxy_weights = {}
        self.min_weight = 0.1
        self.max_weight = 3.0
        self.proxy_fail_count = {}  # Hitung kegagalan
        
        # === GRACEFUL SHUTDOWN ===
        self.running = True
        self.current_futures = []
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)
        
        # Headers standar
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
        
        # Buat file output jika belum ada
        for f in self.output_files.values():
            if not os.path.exists(f):
                open(f, 'a').close()
        
        # Inisialisasi proxy stats
        for proxy in self.proxy_list[:300]:  # Batasi jumlah proxy
            self.proxy_stats[proxy] = {
                'success': 0,
                'fail': 0,
                'total_time': 0,
                'avg_time': 1.0,
                'weight': 1.0
            }
            self.proxy_weights[proxy] = 1.0
            self.proxy_fail_count[proxy] = 0
        
        # === MONITORING STATS ===
        self.stats = {
            'ips_processed': 0,
            'domains_found': 0,
            'errors': 0,
            'start_time': time.time(),
            'last_save': time.time()
        }
        
        # File untuk resume
        self.progress_file = 'scan_progress.txt'
        self.load_progress()
    
    def _create_session(self):
        """Buat session dengan konfigurasi optimal untuk kecepatan"""
        session = requests.Session()
        
        # Konfigurasi adapter dengan pool terbatas
        adapter = requests.adapters.HTTPAdapter(
            pool_connections=20,
            pool_maxsize=30,
            max_retries=1,
            pool_block=True
        )
        session.mount('http://', adapter)
        session.mount('https://', adapter)
        
        # Set default timeout
        session.timeout = (3, 8)
        
        return session
    
    def signal_handler(self, signum, frame):
        """Handle Ctrl+C dan termination signal dengan graceful"""
        print("\n\n[!] Menerima sinyal termination. Menyimpan progress...")
        self.running = False
        
        # Cancel semua future
        for future in self.current_futures:
            future.cancel()
        
        # Simpan progress
        self.save_progress()
        
        print("[*] Menunggu thread selesai (max 3 detik)...")
        time.sleep(3)
        
        self.print_final_stats()
        print("[*] Progress tersimpan. Exiting...")
        sys.exit(0)
    
    def save_progress(self):
        """Simpan progress ke file"""
        try:
            with open(self.progress_file, 'w') as f:
                f.write(f"ips_processed:{self.stats['ips_processed']}\n")
                f.write(f"domains_found:{self.stats['domains_found']}\n")
                f.write(f"errors:{self.stats['errors']}\n")
                f.write(f"last_update:{time.time()}\n")
        except:
            pass
    
    def load_progress(self):
        """Load progress dari file"""
        try:
            if os.path.exists(self.progress_file):
                with open(self.progress_file, 'r') as f:
                    for line in f:
                        if ':' in line:
                            key, val = line.strip().split(':')
                            if key in self.stats and key != 'start_time':
                                self.stats[key] = int(val)
                print(f"[*] Resume progress: {self.stats['ips_processed']} IP已完成")
        except:
            pass
    
    def clean_cache(self):
        """Bersihkan cache jika terlalu besar"""
        if len(self.found_urls) > self.max_cache_size:
            with self.lock:
                items_to_remove = len(self.found_urls) - self.max_cache_size
                for _ in range(items_to_remove):
                    self.found_urls.popitem(last=False)
                gc.collect()
    
    def check_memory_usage(self):
        """Monitor memory usage, return False jika perlu cleanup"""
        if PSUTIL_AVAILABLE:
            try:
                process = psutil.Process(os.getpid())
                memory_usage = process.memory_info().rss / 1024 / 1024  # MB
                
                if memory_usage > 400:  # Jika > 400MB
                    print(f"[!] Memory: {memory_usage:.0f}MB, membersihkan...")
                    gc.collect()
                    
                    # Reset session
                    self.session.close()
                    self.session = self._create_session()
                    
                    return False
            except:
                pass
        return True
    
    def add_to_cache(self, key):
        """Add ke cache dengan LRU"""
        with self.lock:
            self.found_urls[key] = time.time()
            self.found_urls.move_to_end(key)
            self.clean_cache()
    
    def is_cached(self, key):
        """Cek apakah sudah di cache"""
        with self.lock:
            return key in self.found_urls
    
    def update_proxy_stats(self, proxy, success, response_time=None):
        """Update statistik proxy untuk weighted selection"""
        if not proxy or proxy not in self.proxy_stats:
            return
        
        with self.lock:
            stats = self.proxy_stats[proxy]
            
            if success and response_time:
                stats['success'] += 1
                stats['total_time'] += response_time
                total = stats['success'] + stats['fail']
                stats['avg_time'] = stats['total_time'] / total if total > 0 else response_time
                self.proxy_fail_count[proxy] = 0  # Reset fail count
            else:
                stats['fail'] += 1
                self.proxy_fail_count[proxy] = self.proxy_fail_count.get(proxy, 0) + 1
            
            # Hitung ulang bobot setiap 10 request
            total = stats['success'] + stats['fail']
            if total > 0 and total % 10 == 0:
                success_rate = stats['success'] / total
                speed_score = 1.0 / stats['avg_time'] if stats['avg_time'] > 0 else 1.0
                speed_score = min(speed_score, 2.0)
                
                # Penalty untuk proxy yang sering gagal
                fail_penalty = max(0, 1.0 - (self.proxy_fail_count[proxy] / 20))
                
                weight = (success_rate * 0.5 + speed_score * 0.3 + fail_penalty * 0.2) * 2
                stats['weight'] = max(self.min_weight, min(self.max_weight, weight))
                self.proxy_weights[proxy] = stats['weight']
    
    def get_weighted_proxy(self):
        """Dapatkan proxy dengan weighted random selection"""
        if not self.proxy_list:
            return None
        
        try:
            with self.lock:
                # Filter proxy yang masih hidup (fail < 15)
                active_proxies = [
                    p for p in self.proxy_weights 
                    if p in self.proxy_stats and 
                    self.proxy_stats[p]['fail'] < 15
                ]
                
                if not active_proxies:
                    # Reset jika semua proxy gagal
                    for p in self.proxy_stats:
                        self.proxy_stats[p]['fail'] = 0
                        self.proxy_fail_count[p] = 0
                    active_proxies = list(self.proxy_weights.keys())
                
                if not active_proxies:
                    return None
                
                # Weighted random
                weights = [self.proxy_weights[p] for p in active_proxies]
                total_weight = sum(weights)
                
                if total_weight <= 0:
                    proxy = random.choice(active_proxies)
                    return {"http": proxy, "https": proxy}
                
                r = random.uniform(0, total_weight)
                cumulative = 0
                
                for i, proxy in enumerate(active_proxies):
                    cumulative += weights[i]
                    if r <= cumulative:
                        return {"http": proxy, "https": proxy}
                
                # Fallback
                proxy = random.choice(active_proxies)
                return {"http": proxy, "https": proxy}
                
        except Exception:
            return None
    
    def reverse_ip_tntcode(self, ip):
        """Reverse IP via tntcode.com dengan timeout optimal"""
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
            
            response = self.session.get(
                url, 
                headers=headers, 
                proxies=proxies, 
                timeout=(4, 12),
                verify=False
            )
            
            response_time = time.time() - start_time
            
            if proxy_used:
                self.update_proxy_stats(proxy_used, True, response_time)
            
            if response.status_code == 200:
                domains = re.findall(r'<a href="/domain/(.+?)"', response.text)
                return list(set(domains))[:50]  # Batasi 50 domain per IP
            return []
            
        except Exception:
            if proxy_used:
                self.update_proxy_stats(proxy_used, False)
            return []
    
    def reverse_ip_hackertarget(self, ip):
        """Reverse IP via hackertarget.com dengan timeout optimal"""
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
                timeout=(4, 12),
                verify=False
            )
            
            response_time = time.time() - start_time
            
            if proxy_used:
                self.update_proxy_stats(proxy_used, True, response_time)
            
            if response.status_code == 200 and response.text:
                domains = response.text.strip().split('\n')
                return [d for d in domains if d and '.' in d][:50]
            
            return []
            
        except Exception:
            if proxy_used:
                self.update_proxy_stats(proxy_used, False)
            return []
    
    def check_rsd_xml(self, domain):
        """Cek keberadaan rsd.xml dengan timeout cepat"""
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
                        timeout=4,
                        verify=False,
                        allow_redirects=False
                    )
                    
                    if response.status_code == 200 and 'rsd' in response.text.lower():
                        return response.text, url
                except:
                    continue
        return None, None
    
    def extract_mt_info(self, rsd_content):
        """Ekstrak info Movable Type dari rsd.xml"""
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
        api_match = re.search(r'<api[^>]*apiLink="([^"]+)"[^>]*>', rsd_content, re.IGNORECASE)
        if api_match:
            info['api_link'] = api_match.group(1).strip()
            
        return info
    
    def check_mt_endpoints(self, domain, mt_info):
        """Cek endpoint Movable Type"""
        results = []
        
        if not mt_info['api_link']:
            return results
        
        # Generate URLs
        xmlrpc_urls = []
        if mt_info['api_link'].startswith('http'):
            xmlrpc_urls.append(mt_info['api_link'])
        else:
            xmlrpc_urls.append(f"http://{domain}{mt_info['api_link']}")
            xmlrpc_urls.append(f"https://{domain}{mt_info['api_link']}")
        
        for xmlrpc_url in xmlrpc_urls:
            cache_key = f"{xmlrpc_url}|check"
            if self.is_cached(cache_key):
                continue
            
            try:
                headers = self.headers.copy()
                headers["User-Agent"] = self.ua.random
                
                response = self.session.get(
                    xmlrpc_url, 
                    headers=headers, 
                    timeout=5,
                    allow_redirects=False,
                    verify=False
                )
                
                is_v4 = mt_info.get('version', '').startswith('4')
                
                # Cek status code yang menandakan adanya mt-xmlrpc.cgi
                if response.status_code in [403, 411, 405, 200]:
                    url_key = f"{xmlrpc_url}|{response.status_code}"
                    
                    if not self.is_cached(url_key):
                        self.add_to_cache(url_key)
                        
                        # Simpan ke file
                        with open(self.output_files['movable_type'], 'a') as f:
                            f.write(f"{xmlrpc_url}\n")
                        
                        display_url = xmlrpc_url.replace('http://', '').replace('https://', '')
                        print(f"[+] MT ditemukan: {display_url} ({response.status_code})")
                        
                        results.append({
                            'domain': domain,
                            'xmlrpc_url': xmlrpc_url,
                            'xmlrpc_status': response.status_code,
                            'version': mt_info.get('version'),
                            'is_v4': is_v4
                        })
                        
                        # Cek mt-upgrade.cgi untuk versi 4
                        if is_v4:
                            upgrade_url = xmlrpc_url.replace('mt-xmlrpc.cgi', 'mt-upgrade.cgi')
                            if upgrade_url != xmlrpc_url:
                                try:
                                    upgrade_response = self.session.get(
                                        upgrade_url, 
                                        headers=headers, 
                                        timeout=5,
                                        allow_redirects=False,
                                        verify=False
                                    )
                                    
                                    if upgrade_response.status_code == 200:
                                        upgrade_key = f"{upgrade_url}|200"
                                        if not self.is_cached(upgrade_key):
                                            self.add_to_cache(upgrade_key)
                                            
                                            with open(self.output_files['movable_type_v4'], 'a') as f:
                                                f.write(f"{upgrade_url}\n")
                                            
                                            print(f"[!] MT v4 upgrade: {upgrade_url}")
                                except:
                                    pass
                
                self.add_to_cache(cache_key)
                
            except Exception:
                self.add_to_cache(cache_key)
                continue
        
        return results
    
    def scan_domain(self, domain):
        """Scan satu domain"""
        if not self.running or not domain:
            return []
        
        domain = domain.lower().strip()
        if domain in self.found_domains:
            return []
        
        try:
            rsd_content, rsd_url = self.check_rsd_xml(domain)
            
            if rsd_content:
                mt_info = self.extract_mt_info(rsd_content)
                
                if mt_info['engine'] and 'movable type' in mt_info['engine'].lower():
                    self.found_domains.add(domain)
                    return self.check_mt_endpoints(domain, mt_info)
        except Exception:
            pass
        
        return []
    
    def process_ip(self, ip):
        """Process satu IP"""
        if not self.running:
            return
        
        # Cek memory
        self.check_memory_usage()
        
        with self.lock:
            self.stats['ips_processed'] += 1
            current_ip = self.stats['ips_processed']
        
        print(f"\n[*] IP {current_ip}: {ip}")
        
        # Reverse IP
        domains_tnt = self.reverse_ip_tntcode(ip)
        domains_ht = self.reverse_ip_hackertarget(ip)
        
        all_domains = list(set(domains_tnt + domains_ht))
        
        if all_domains:
            print(f"[+] Domain: {len(all_domains)}")
            
            # Batch processing
            found = 0
            batch_size = 15
            
            for i in range(0, len(all_domains), batch_size):
                if not self.running:
                    break
                
                batch = all_domains[i:i+batch_size]
                
                with ThreadPoolExecutor(max_workers=10) as executor:
                    futures = [executor.submit(self.scan_domain, d) for d in batch]
                    self.current_futures = futures
                    
                    for future in as_completed(futures):
                        if not self.running:
                            break
                        try:
                            results = future.result(timeout=8)
                            if results:
                                found += len(results)
                                with self.lock:
                                    self.stats['domains_found'] += len(results)
                        except Exception:
                            with self.lock:
                                self.stats['errors'] += 1
                    
                    self.current_futures = []
                
                # Delay antar batch
                time.sleep(0.5)
            
            print(f"[+] IP {ip}: {found} MT ditemukan")
        else:
            print(f"[-] Tidak ada domain")
        
        # Save progress setiap 10 IP
        if current_ip % 10 == 0:
            self.save_progress()
            self.print_stats()
    
    def print_stats(self):
        """Tampilkan statistik实时"""
        elapsed = time.time() - self.stats['start_time']
        speed = self.stats['ips_processed'] / elapsed * 60 if elapsed > 0 else 0
        
        print(f"\n[STATS] {self.stats['ips_processed']} IP dalam {elapsed:.0f}s")
        print(f"[STATS] Kecepatan: {speed:.1f} IP/menit")
        print(f"[STATS] Ditemukan: {self.stats['domains_found']}")
        print(f"[STATS] Errors: {self.stats['errors']}")
    
    def print_final_stats(self):
        """Tampilkan statistik final"""
        elapsed = time.time() - self.stats['start_time']
        hours = elapsed // 3600
        minutes = (elapsed % 3600) // 60
        seconds = elapsed % 60
        
        print("\n" + "="*60)
        print("STATISTIK FINAL")
        print("="*60)
        print(f"Waktu total: {int(hours)}j {int(minutes)}m {int(seconds)}d")
        print(f"IP diproses: {self.stats['ips_processed']}")
        print(f"MT ditemukan: {self.stats['domains_found']}")
        print(f"Total errors: {self.stats['errors']}")
        print(f"Kecepatan rata-rata: {self.stats['ips_processed']/elapsed*60:.1f} IP/menit")
        
        # Tampilkan proxy terbaik
        if self.proxy_stats:
            print("\nProxy Terbaik:")
            sorted_proxies = sorted(
                self.proxy_stats.items(), 
                key=lambda x: x[1]['weight'], 
                reverse=True
            )[:5]
            
            for proxy, stats in sorted_proxies:
                if stats['success'] + stats['fail'] > 0:
                    success_rate = stats['success'] / (stats['success'] + stats['fail']) * 100
                    print(f"  {proxy}: {success_rate:.0f}% success, {stats['avg_time']:.2f}s")
    
    def scan_from_file(self, filename):
        """Scan dari file list IP"""
        try:
            if not os.path.exists(filename):
                print(f"[!] File {filename} tidak ditemukan!")
                return
            
            with open(filename, 'r') as f:
                all_ips = [line.strip() for line in f if line.strip() and not line.startswith('#')]
            
            # Filter IP valid
            valid_ips = []
            for ip in all_ips:
                parts = ip.split('.')
                if len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
                    valid_ips.append(ip)
            
            print(f"[*] Total IP: {len(valid_ips)} dari {len(all_ips)}")
            
            # Resume dari progress
            processed_file = 'processed_ips.txt'
            processed = set()
            if os.path.exists(processed_file):
                with open(processed_file, 'r') as pf:
                    processed = set([line.strip() for line in pf])
            
            ips_to_scan = [ip for ip in valid_ips if ip not in processed]
            print(f"[*] Sisa scan: {len(ips_to_scan)} IP")
            
            for i, ip in enumerate(ips_to_scan):
                if not self.running:
                    break
                
                self.process_ip(ip)
                
                # Simpan progress
                with open(processed_file, 'a') as pf:
                    pf.write(f"{ip}\n")
                
                # Delay antar IP
                time.sleep(1)
            
            self.print_final_stats()
            
        except Exception as e:
            print(f"[!] Error: {e}")
    
    def scan_random_ips(self, base_ip, count=50):
        """Scan dengan IP random"""
        try:
            # Validasi base IP
            parts = base_ip.split('.')
            if len(parts) == 3:
                base_ip = f"{base_ip}.1"
            elif len(parts) != 4:
                print("[!] Format IP tidak valid!")
                return
            
            base_parts = base_ip.split('.')
            base = '.'.join(base_parts[:3]) + '.'
            
            print(f"[*] Generating {count} random IPs from {base}[1-254]...")
            
            valid_ips = []
            attempted = set()
            
            while len(valid_ips) < count and len(attempted) < 254:
                last = random.randint(1, 254)
                ip = base + str(last)
                
                if ip in attempted:
                    continue
                
                attempted.add(ip)
                
                # Quick check via socket
                try:
                    socket.gethostbyaddr(ip)
                    valid_ips.append(ip)
                    print(f"[+] Valid IP: {ip} ({len(valid_ips)}/{count})")
                except:
                    continue
            
            print(f"[*] Found {len(valid_ips)} valid IPs")
            
            for ip in valid_ips:
                if not self.running:
                    break
                self.process_ip(ip)
                time.sleep(1)
            
            self.print_final_stats()
            
        except Exception as e:
            print(f"[!] Error: {e}")


def download_proxy_list():
    """Download proxy list dari GitHub"""
    proxy_urls = [
        "https://raw.githubusercontent.com/proxifly/free-proxy-list/refs/heads/main/proxies/all/data.txt",
        "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
        "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt"
    ]
    
    all_proxies = []
    
    for url in proxy_urls:
        try:
            print(f"[*] Downloading proxy from: {url}")
            headers = {"User-Agent": "Mozilla/5.0"}
            
            response = requests.get(url, headers=headers, timeout=15, verify=False)
            
            if response.status_code == 200:
                proxies = []
                for line in response.text.split('\n'):
                    line = line.strip()
                    if line and '://' in line:
                        proxies.append(line)
                    elif line and ':' in line and not line.startswith('#'):
                        # Format ip:port, tambahkan http://
                        proxies.append(f"http://{line}")
                
                all_proxies.extend(proxies)
                print(f"[+] Got {len(proxies)} proxies")
        except Exception as e:
            print(f"[-] Failed: {str(e)[:30]}")
            continue
    
    # Hapus duplikat
    all_proxies = list(set(all_proxies))
    
    # Filter format valid
    valid_proxies = [p for p in all_proxies if p.startswith(('http://', 'https://', 'socks4://', 'socks5://'))]
    
    print(f"[+] Total unique proxies: {len(valid_proxies)}")
    return valid_proxies[:300]  # Batasi 300 proxy terbaik


def main():
    """Main function"""
    print("""
╔══════════════════════════════════════════════════════════╗
║     Movable Type Mass Scanner v2.0 - STABLE             ║
║  ═════════════════════════════════════════════════════   ║
║  ✓ Anti-Memory Leak          ✓ Weighted Proxy          ║
║  ✓ Graceful Shutdown         ✓ SSL Verify Disabled     ║
║  ✓ Resume Capability         ✓ Auto Batch Processing   ║
║  ✓ Real-time Stats           ✓ Memory Monitoring       ║
╚══════════════════════════════════════════════════════════╝
    """)
    
    print("[*] Mengambil proxy list...")
    proxies = download_proxy_list()
    
    if proxies:
        print(f"[+] Menggunakan {len(proxies)} proxy")
    else:
        print("[!] Tidak ada proxy, melanjutkan tanpa proxy...")
    
    # Inisialisasi scanner
    scanner = MovableTypeScanner(
        proxy_list=proxies,
        max_threads=25,  # Kurangi thread untuk stabilitas
        max_valid_rng=50
    )
    
    # Menu
    print("\nPilih metode input:")
    print("1. Scan dari file list IP")
    print("2. Scan dengan RNG IP (random)")
    print("3. Exit")
    
    choice = input("\nPilihan (1-3): ").strip()
    
    if choice == '1':
        filename = input("Nama file list IP: ").strip()
        if filename:
            scanner.scan_from_file(filename)
    
    elif choice == '2':
        base_ip = input("Base IP (contoh: 157.7.44): ").strip()
        if base_ip:
            try:
                count = int(input("Jumlah IP random (default 50): ").strip() or "50")
                scanner.scan_random_ips(base_ip, count)
            except:
                scanner.scan_random_ips(base_ip, 50)
    
    else:
        print("[*] Exiting...")
        return
    
    print("\n[*] Scan selesai!")
    print(f"[*] Hasil di: {scanner.output_files['movable_type']} dan {scanner.output_files['movable_type_v4']}")


if __name__ == "__main__":
    main()
