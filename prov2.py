import requests
import re
import time
import random
import threading
from queue import Queue, Empty
from fake_useragent import UserAgent
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed
import sys
import os
from colorama import init, Fore, Back, Style
import itertools

# Inisialisasi colorama untuk Windows/Linux
init(autoreset=True)

# Animasi loading
class Spinner:
    def __init__(self, message="Loading", delay=0.1):
        self.spinner = itertools.cycle(['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'])
        self.delay = delay
        self.message = message
        self.running = False
        self.thread = None
    
    def spin(self):
        while self.running:
            sys.stdout.write(f"\r{Fore.CYAN}{next(self.spinner)} {self.message}{Style.RESET_ALL}")
            sys.stdout.flush()
            time.sleep(self.delay)
    
    def start(self):
        self.running = True
        self.thread = threading.Thread(target=self.spin)
        self.thread.start()
    
    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join()
        sys.stdout.write("\r" + " " * 80 + "\r")
        sys.stdout.flush()

class ProgressBar:
    def __init__(self, total, prefix='', suffix='', length=30):
        self.total = total
        self.prefix = prefix
        self.suffix = suffix
        self.length = length
        self.current = 0
    
    def update(self, n=1):
        self.current += n
        percent = 100 * (self.current / float(self.total))
        filled_length = int(self.length * self.current // self.total)
        bar = f"{Fore.GREEN}{'█' * filled_length}{Fore.WHITE}{'░' * (self.length - filled_length)}{Style.RESET_ALL}"
        
        sys.stdout.write(f"\r{self.prefix} |{bar}| {Fore.YELLOW}{percent:.1f}%{Style.RESET_ALL} {self.suffix}")
        sys.stdout.flush()
        
        if self.current == self.total:
            print()

class MovableTypeScanner:
    def __init__(self, max_threads=50, max_valid_rng=50):
        self.ua = UserAgent()
        self.max_threads = max_threads
        self.max_valid_rng = max_valid_rng
        self.session = requests.Session()
        self.found_urls = set()
        
        # Proxy management
        self.all_proxies = []
        self.active_proxies = Queue()
        self.proxy_lock = threading.Lock()
        self.proxy_failures = {}
        self.max_failures_per_proxy = 3
        self.current_proxy_display = ""
        
        # Headers
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
        
        # Stats
        self.stats = {
            'total_ips': 0,
            'processed_ips': 0,
            'domains_found': 0,
            'movable_type_found': 0,
            'movable_type_v4_found': 0,
            'failed_reverse': 0,
            'proxy_switches': 0,
            'total_proxies': 0
        }
        
        # Untuk animasi
        self.current_ip_line = ""
        self.last_line_length = 0
    
    def clear_line(self):
        """Menghapus line sebelumnya"""
        sys.stdout.write('\r' + ' ' * self.last_line_length + '\r')
        sys.stdout.flush()
    
    def print_status(self, message, color=Fore.WHITE, icon="•", end="\n"):
        """Print dengan format konsisten"""
        line = f"{color}{icon} {message}{Style.RESET_ALL}"
        self.last_line_length = len(line)
        print(line, end=end)
    
    def print_success(self, message, icon="✓"):
        self.print_status(message, Fore.GREEN, icon)
    
    def print_error(self, message, icon="✗"):
        self.print_status(message, Fore.RED, icon)
    
    def print_info(self, message, icon="ℹ"):
        self.print_status(message, Fore.CYAN, icon)
    
    def print_warning(self, message, icon="⚠"):
        self.print_status(message, Fore.YELLOW, icon)
    
    def print_bold(self, message, color=Fore.WHITE):
        print(f"{Style.BRIGHT}{color}{message}{Style.RESET_ALL}")
    
    def print_header(self, message):
        print(f"\n{Fore.MAGENTA}{Style.BRIGHT}{'='*60}{Style.RESET_ALL}")
        print(f"{Fore.MAGENTA}{Style.BRIGHT}║ {message:^56} ║{Style.RESET_ALL}")
        print(f"{Fore.MAGENTA}{Style.BRIGHT}{'='*60}{Style.RESET_ALL}")
    
    def print_ip_header(self, ip, current, total):
        """Header untuk setiap IP"""
        print(f"\n{Fore.BLUE}{Style.BRIGHT}[{current}/{total}] Memproses IP: {Fore.YELLOW}{ip}{Style.RESET_ALL}")
        print(f"{Fore.BLUE}{'─'*60}{Style.RESET_ALL}")
    
    def validate_proxy(self, proxy):
        """Validasi apakah proxy benar-benar bekerja"""
        test_url = "http://httpbin.org/ip"
        proxy_dict = {"http": proxy, "https": proxy}
        
        for attempt in range(2):
            try:
                start_time = time.time()
                response = self.session.get(
                    test_url, 
                    proxies=proxy_dict, 
                    timeout=10,
                    headers={"User-Agent": self.ua.random}
                )
                response_time = time.time() - start_time
                
                if response.status_code == 200:
                    return True, response_time
                else:
                    time.sleep(1)
            except:
                if attempt == 0:
                    time.sleep(2)
                continue
        
        return False, None
    
    def get_active_proxies(self, min_proxies=20):
        """Mendapatkan dan memvalidasi proxy aktif"""
        self.print_header("TAHAP 0: VALIDASI PROXY")
        
        # Download proxy list
        proxy_url = "https://raw.githubusercontent.com/proxifly/free-proxy-list/refs/heads/main/proxies/countries/SG/data.txt"
        
        try:
            self.print_info("Mendownload proxy list...", icon="📥")
            
            spinner = Spinner("Mengunduh proxy...")
            spinner.start()
            
            response = requests.get(proxy_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
            
            spinner.stop()
            
            if response.status_code == 200:
                proxies = [line.strip() for line in response.text.split('\n') if line.strip()]
                proxies = [p for p in proxies if '://' in p]
                self.print_success(f"Mendapatkan {len(proxies)} proxy untuk divalidasi")
                
                self.print_info("Memvalidasi 100 proxy pertama... (Target minimal 20 aktif)")
                
                active_proxies = []
                
                # Buat progress bar untuk validasi
                pb = ProgressBar(100, prefix=f"{Fore.CYAN}Validasi:{Style.RESET_ALL}", suffix="proxy")
                
                with ThreadPoolExecutor(max_workers=30) as executor:
                    future_to_proxy = {executor.submit(self.validate_proxy, proxy): proxy for proxy in proxies[:100]}
                    
                    for i, future in enumerate(as_completed(future_to_proxy), 1):
                        is_active, response_time = future.result()
                        if is_active:
                            proxy = future_to_proxy[future]
                            active_proxies.append((proxy, response_time))
                        pb.update()
                
                # Urutkan berdasarkan response time
                active_proxies.sort(key=lambda x: x[1])
                
                print()
                self.print_success(f"Total proxy aktif: {len(active_proxies)}")
                
                if active_proxies:
                    # Masukkan ke queue
                    for proxy, _ in active_proxies:
                        self.active_proxies.put(proxy)
                        self.all_proxies.append(proxy)
                    
                    self.stats['total_proxies'] = len(active_proxies)
                    
                    # Tampilkan 3 proxy tercepat
                    self.print_info("3 Proxy tercepat:")
                    for i, (proxy, resp_time) in enumerate(active_proxies[:3], 1):
                        print(f"  {Fore.GREEN}{i}.{Style.RESET_ALL} {Fore.YELLOW}{proxy}{Style.RESET_ALL} {Fore.CYAN}({resp_time:.2f}s){Style.RESET_ALL}")
                    
                    return True
                else:
                    self.print_error("Tidak ada proxy aktif!")
                    return False
            else:
                self.print_error(f"Gagal download proxy: {response.status_code}")
                return False
                
        except Exception as e:
            spinner.stop()
            self.print_error(f"Error: {str(e)[:50]}")
            return False
    
    def get_proxy_with_retry(self):
        """Mendapatkan proxy dari queue"""
        try:
            proxy = self.active_proxies.get_nowait()
            self.active_proxies.put(proxy)
            self.current_proxy_display = proxy
            return {"http": proxy, "https": proxy}
        except Empty:
            if self.all_proxies:
                random.shuffle(self.all_proxies)
                for p in self.all_proxies:
                    self.active_proxies.put(p)
                return self.get_proxy_with_retry()
            return None
    
    def reverse_ip_service(self, ip, service_name, service_func, max_retries=3):
        """Generic reverse IP dengan retry dan animasi"""
        attempt = 1
        last_error = ""
        
        while attempt <= max_retries:
            # Dapatkan proxy
            proxy_dict = self.get_proxy_with_retry()
            if not proxy_dict:
                self.print_error("Tidak ada proxy tersedia!")
                return [], False
            
            proxy_str = list(proxy_dict.values())[0]
            
            # Animasi loading
            spinner = Spinner(f"{service_name} attempt {attempt}/{max_retries}")
            spinner.start()
            
            try:
                domains, error = service_func(ip, proxy_dict)
                spinner.stop()
                
                if domains:
                    return domains, True
                else:
                    if error and ("SOCKS" in error or "HTTPSConnectionPool" in error):
                        self.print_warning(f"{service_name} gagal (attempt {attempt}): {error[:60]}...")
                        self.print_info(f"Mengganti proxy... (Proxy: {proxy_str})")
                        self.mark_proxy_failed(proxy_str)
                        self.stats['proxy_switches'] += 1
                        attempt += 1
                        time.sleep(1)
                    else:
                        # Error lain (bukan proxy error)
                        if error:
                            self.print_error(f"{service_name} error: {error[:60]}...")
                        return [], False
                        
            except Exception as e:
                spinner.stop()
                error_msg = str(e)
                if "SOCKS" in error_msg or "HTTPSConnectionPool" in error_msg:
                    self.print_warning(f"{service_name} gagal (attempt {attempt}): {error_msg[:60]}...")
                    self.print_info(f"Mengganti proxy... (Proxy: {proxy_str})")
                    self.mark_proxy_failed(proxy_str)
                    self.stats['proxy_switches'] += 1
                    attempt += 1
                    time.sleep(1)
                else:
                    self.print_error(f"{service_name} error: {error_msg[:60]}...")
                    return [], False
        
        return [], False
    
    def reverse_ip_tntcode(self, ip, proxy):
        """Reverse IP menggunakan tntcode.com"""
        try:
            url = f"https://domains.tntcode.com/ip/{ip}"
            headers = self.headers.copy()
            headers["User-Agent"] = self.ua.random
            
            response = self.session.get(url, headers=headers, proxies=proxy, timeout=30)
            domains = re.findall(r'<a href="/domain/(.+?)"', response.text)
            return domains, None
        except Exception as e:
            return [], str(e)
    
    def reverse_ip_hackertarget(self, ip, proxy):
        """Reverse IP menggunakan hackertarget.com"""
        try:
            url = f"https://api.hackertarget.com/reverseiplookup/?q={ip}"
            headers = self.headers.copy()
            headers["User-Agent"] = self.ua.random
            
            response = self.session.get(url, headers=headers, proxies=proxy, timeout=30)
            
            if response.text and "error" not in response.text.lower():
                domains = response.text.strip().split('\n')
                # Filter domain yang valid (minimal ada titik)
                domains = [d for d in domains if '.' in d and len(d) > 3]
                return domains, None
            return [], None
        except Exception as e:
            return [], str(e)
    
    def reverse_ip_phase1(self, ip):
        """TAHAP 1: Reverse IP dengan tampilan per IP"""
        
        # TNTCode
        tnt_domains, tnt_success = self.reverse_ip_service(
            ip, "TNTCode", self.reverse_ip_tntcode
        )
        
        # HackerTarget
        ht_domains, ht_success = self.reverse_ip_service(
            ip, "HackerTarget", self.reverse_ip_hackertarget
        )
        
        # Gabungkan hasil
        all_domains = list(set(tnt_domains + ht_domains))
        
        # Tampilkan hasil
        if tnt_success:
            self.print_success(f"TNTCode: {Fore.YELLOW}{len(tnt_domains)} domain")
        else:
            self.print_error("TNTCode: Gagal")
            
        if ht_success:
            self.print_success(f"HackerTarget: {Fore.YELLOW}{len(ht_domains)} domain")
        else:
            self.print_error("HackerTarget: Gagal")
        
        if all_domains:
            self.print_success(f"TOTAL: {Fore.YELLOW}{len(all_domains)} domain unik", icon="🎯")
            self.stats['domains_found'] += len(all_domains)
            return all_domains
        else:
            self.print_error("Tidak ada domain ditemukan!", icon="😞")
            self.stats['failed_reverse'] += 1
            return []
    
    def mark_proxy_failed(self, proxy_str):
        """Tandai proxy yang gagal"""
        with self.proxy_lock:
            self.proxy_failures[proxy_str] = self.proxy_failures.get(proxy_str, 0) + 1
            
            if self.proxy_failures[proxy_str] >= self.max_failures_per_proxy:
                # Hapus dari queue
                new_queue = Queue()
                while not self.active_proxies.empty():
                    p = self.active_proxies.get()
                    if p != proxy_str:
                        new_queue.put(p)
                self.active_proxies = new_queue
    
    def scan_domains_phase2(self, ip, domains):
        """TAHAP 2: Scan domain untuk Movable Type dengan progress bar"""
        if not domains:
            return
        
        print()
        self.print_info(f"Memindai {Fore.YELLOW}{len(domains)}{Style.RESET_ALL} domain dari IP {Fore.YELLOW}{ip}{Style.RESET_ALL}")
        
        found_count = 0
        v4_count = 0
        scanned = 0
        total = len(domains)
        
        # Progress bar untuk scanning
        pb = ProgressBar(total, prefix=f"{Fore.CYAN}Scan:{Style.RESET_ALL}", suffix="domain")
        
        # List untuk menyimpan hasil yang ditemukan
        mt_results = []
        
        for domain in domains:
            results = self.scan_domain(domain)
            if results:
                for result in results:
                    if result.get('is_v4') and result.get('upgrade_found'):
                        v4_count += 1
                        mt_results.append(('v4', result))
                    else:
                        found_count += 1
                        mt_results.append(('normal', result))
            scanned += 1
            pb.update()
        
        # Tampilkan hasil temuan dalam format ringkas
        if mt_results:
            print()
            for result_type, result in mt_results:
                if result_type == 'normal':
                    version = f"v{result['version']}" if result.get('version') else "Unknown"
                    status = result.get('xmlrpc_status', '?')
                    print(f"  {Fore.GREEN}🔥{Style.RESET_ALL} Movable Type: {Fore.YELLOW}{result['display_url']}{Style.RESET_ALL} ({Fore.RED}{status}{Style.RESET_ALL}) - {Fore.CYAN}{version}{Style.RESET_ALL}")
                else:
                    version = f"v{result['version']}" if result.get('version') else "v4.x"
                    print(f"  {Fore.RED}⚡{Style.RESET_ALL} MT v4 Upgrade: {Fore.YELLOW}{result['upgrade_url']}{Style.RESET_ALL} ({Fore.GREEN}200{Style.RESET_ALL}) - {Fore.CYAN}{version}{Style.RESET_ALL}")
            
            total_found = found_count + v4_count
            self.print_success(f"Ditemukan {Fore.YELLOW}{total_found}{Style.RESET_ALL} Movable Type ({Fore.GREEN}{found_count} normal{Style.RESET_ALL}, {Fore.RED}{v4_count} upgrade{Style.RESET_ALL})", icon="🔥")
            self.stats['movable_type_found'] += total_found
            self.stats['movable_type_v4_found'] += v4_count
        else:
            self.print_info("Tidak ditemukan", icon="🔍")
    
    def check_rsd_xml(self, domain):
        """Memeriksa keberadaan rsd.xml"""
        paths = ['/rsd.xml', '/blog/rsd.xml']
        
        for path in paths:
            for protocol in ['http', 'https']:
                try:
                    url = f"{protocol}://{domain}{path}"
                    headers = self.headers.copy()
                    headers["User-Agent"] = self.ua.random
                    
                    response = self.session.get(url, headers=headers, timeout=10)
                    
                    if response.status_code == 200 and 'rsd' in response.text.lower():
                        return response.text, url
                except:
                    continue
        return None, None
    
    def extract_mt_info(self, rsd_content):
        """Mengekstrak informasi Movable Type"""
        info = {'engine': None, 'api_link': None, 'version': None}
        
        engine_match = re.search(r'<engineName>(.+?)</engineName>', rsd_content, re.IGNORECASE)
        if engine_match:
            info['engine'] = engine_match.group(1)
            if 'movable type' in info['engine'].lower():
                version_match = re.search(r'(\d+\.\d+)', info['engine'])
                if version_match:
                    info['version'] = version_match.group(1)
        
        api_match = re.search(r'<api[^>]*apiLink="([^"]+)"[^>]*>', rsd_content, re.IGNORECASE)
        if api_match:
            info['api_link'] = api_match.group(1).strip()
            
        return info
    
    def scan_domain(self, domain):
        """Scan satu domain untuk Movable Type"""
        try:
            rsd_content, rsd_url = self.check_rsd_xml(domain)
            
            if rsd_content:
                mt_info = self.extract_mt_info(rsd_content)
                
                if mt_info['engine'] and 'movable type' in mt_info['engine'].lower():
                    return self.check_mt_endpoints(domain, mt_info)
        except Exception:
            pass
        return []
    
    def check_mt_endpoints(self, domain, mt_info):
        """Memeriksa endpoint Movable Type dengan output ringkas"""
        results = []
        
        if mt_info['api_link']:
            xmlrpc_urls = []
            
            if mt_info['api_link'].startswith('http'):
                xmlrpc_urls.append(mt_info['api_link'])
            else:
                xmlrpc_urls.append(f"http://{domain}{mt_info['api_link']}")
                xmlrpc_urls.append(f"https://{domain}{mt_info['api_link']}")
            
            for xmlrpc_url in xmlrpc_urls:
                try:
                    headers = self.headers.copy()
                    headers["User-Agent"] = self.ua.random
                    
                    response = self.session.get(xmlrpc_url, headers=headers, timeout=10, allow_redirects=False)
                    
                    is_v4 = mt_info.get('version') and mt_info['version'].startswith('4')
                    version_display = mt_info.get('version', 'Unknown')
                    
                    if response.status_code in [403, 411, 405]:
                        url_key = f"{xmlrpc_url}|{response.status_code}"
                        if url_key in self.found_urls:
                            continue
                        
                        self.found_urls.add(url_key)
                        
                        with open(self.output_files['movable_type'], 'a') as f:
                            f.write(f"{xmlrpc_url}\n")
                        
                        display_url = xmlrpc_url.replace('http://', '').replace('https://', '')
                        
                        result = {
                            'domain': domain,
                            'xmlrpc_url': xmlrpc_url,
                            'display_url': display_url,
                            'xmlrpc_status': response.status_code,
                            'version': version_display,
                            'is_v4': is_v4,
                            'engine': mt_info['engine'],
                            'upgrade_found': False
                        }
                        
                        results.append(result)
                    
                    # Cek mt-upgrade.cgi untuk versi 4
                    if is_v4:
                        upgrade_url = xmlrpc_url.replace('mt-xmlrpc.cgi', 'mt-upgrade.cgi')
                        
                        if upgrade_url != xmlrpc_url:
                            try:
                                upgrade_response = self.session.get(upgrade_url, headers=headers, timeout=10, allow_redirects=False)
                                if upgrade_response.status_code == 200:
                                    upgrade_key = f"{upgrade_url}|200"
                                    if upgrade_key not in self.found_urls:
                                        self.found_urls.add(upgrade_key)
                                        
                                        with open(self.output_files['movable_type_v4'], 'a') as f:
                                            f.write(f"{upgrade_url}\n")
                                        
                                        display_upgrade = upgrade_url.replace('http://', '').replace('https://', '')
                                        
                                        # Buat result khusus untuk upgrade
                                        upgrade_result = {
                                            'domain': domain,
                                            'xmlrpc_url': xmlrpc_url,
                                            'upgrade_url': display_upgrade,
                                            'xmlrpc_status': response.status_code,
                                            'version': version_display,
                                            'is_v4': is_v4,
                                            'engine': mt_info['engine'],
                                            'upgrade_found': True
                                        }
                                        results.append(upgrade_result)
                            except:
                                pass
                
                except Exception:
                    continue
        
        return results
    
    def scan_from_file(self, filename):
        """Main scanning process"""
        try:
            with open(filename, 'r') as f:
                ips = [line.strip() for line in f if line.strip()]
            
            self.stats['total_ips'] = len(ips)
            print()
            self.print_info(f"Memuat {Fore.YELLOW}{len(ips)}{Style.RESET_ALL} IP dari file {Fore.CYAN}{filename}{Style.RESET_ALL}")
            
            # TAHAP 0: Validasi Proxy
            if not self.get_active_proxies():
                self.print_error("Tidak bisa melanjutkan tanpa proxy aktif!")
                return
            
            # TAHAP 1: Reverse IP per IP
            self.print_header(f"TAHAP 1: REVERSE IP ({self.stats['total_ips']} IP)")
            
            phase1_results = []
            
            for idx, ip in enumerate(ips, 1):
                self.print_ip_header(ip, idx, self.stats['total_ips'])
                
                # Reverse IP untuk IP ini
                domains = self.reverse_ip_phase1(ip)
                phase1_results.append((ip, domains))
                self.stats['processed_ips'] += 1
            
            # TAHAP 2: Scan Domain
            self.print_header("TAHAP 2: SCANNING DOMAIN")
            
            for ip, domains in phase1_results:
                self.scan_domains_phase2(ip, domains)
            
            # Tampilkan statistik
            self.print_final_stats()
                        
        except Exception as e:
            self.print_error(f"Error: {str(e)}")
    
    def scan_random_ips(self, base_ip):
        """Scan dengan IP random"""
        valid_ips = self.generate_random_ips(base_ip)
        
        if valid_ips:
            self.stats['total_ips'] = len(valid_ips)
            print()
            self.print_info(f"Memulai scan untuk {Fore.YELLOW}{len(valid_ips)}{Style.RESET_ALL} IP valid...")
            
            # TAHAP 0: Validasi Proxy
            if not self.get_active_proxies():
                self.print_error("Tidak bisa melanjutkan tanpa proxy aktif!")
                return
            
            # TAHAP 1: Reverse IP per IP
            self.print_header(f"TAHAP 1: REVERSE IP ({self.stats['total_ips']} IP)")
            
            phase1_results = []
            
            for idx, ip in enumerate(valid_ips, 1):
                self.print_ip_header(ip, idx, self.stats['total_ips'])
                
                # Reverse IP untuk IP ini
                domains = self.reverse_ip_phase1(ip)
                phase1_results.append((ip, domains))
                self.stats['processed_ips'] += 1
            
            # TAHAP 2: Scan Domain
            self.print_header("TAHAP 2: SCANNING DOMAIN")
            
            for ip, domains in phase1_results:
                self.scan_domains_phase2(ip, domains)
            
            # Tampilkan statistik
            self.print_final_stats()
    
    def generate_random_ips(self, base_ip):
        """Menghasilkan IP random"""
        base_parts = base_ip.split('.')
        if len(base_parts) != 4:
            self.print_error("Format IP tidak valid!")
            return []
        
        base = '.'.join(base_parts[:3]) + '.'
        valid_ips = []
        attempted = set()
        
        self.print_info(f"Mencari {Fore.YELLOW}{self.max_valid_rng}{Style.RESET_ALL} IP valid dari {Fore.CYAN}{base}[1-254]{Style.RESET_ALL}")
        
        pb = ProgressBar(self.max_valid_rng, prefix=f"{Fore.CYAN}Generate:{Style.RESET_ALL}", suffix="IP valid")
        
        while len(valid_ips) < self.max_valid_rng and len(attempted) < 254:
            last_octet = random.randint(1, 254)
            ip = base + str(last_octet)
            
            if ip in attempted:
                continue
                
            attempted.add(ip)
            
            if self.check_ip_valid(ip):
                valid_ips.append(ip)
                pb.update()
        
        print()
        return valid_ips
    
    def check_ip_valid(self, ip):
        """Memeriksa validitas IP"""
        try:
            socket.gethostbyaddr(ip)
            return True
        except:
            return False
    
    def print_final_stats(self):
        """Menampilkan statistik akhir"""
        self.print_header("STATISTIK SCAN")
        
        stats_lines = [
            (f"Total IP diproses", f"{self.stats['processed_ips']}/{self.stats['total_ips']}"),
            (f"Total domain ditemukan", f"{self.stats['domains_found']}"),
            (f"Movable Type ditemukan", f"{self.stats['movable_type_found']}"),
            (f"  └─ Normal", f"{self.stats['movable_type_found'] - self.stats['movable_type_v4_found']}"),
            (f"  └─ v4 Upgrade", f"{self.stats['movable_type_v4_found']}"),
            (f"IP tanpa domain", f"{self.stats['failed_reverse']}"),
            (f"Proxy switch total", f"{self.stats['proxy_switches']}"),
            (f"Total proxy aktif", f"{self.stats['total_proxies']}")
        ]
        
        for label, value in stats_lines:
            print(f"{Fore.CYAN}║{Style.RESET_ALL} {label:<25}: {Fore.YELLOW}{value}{Style.RESET_ALL}")
        
        print(f"{Fore.CYAN}{'='*60}{Style.RESET_ALL}")
        
        # Info file output
        print(f"\n{Fore.GREEN}📁 Hasil disimpan di:{Style.RESET_ALL}")
        print(f"  {Fore.YELLOW}• {self.output_files['movable_type']}{Style.RESET_ALL} ({self.stats['movable_type_found'] - self.stats['movable_type_v4_found']} URL)")
        print(f"  {Fore.YELLOW}• {self.output_files['movable_type_v4']}{Style.RESET_ALL} ({self.stats['movable_type_v4_found']} URL)")


def main():
    # Clear screen
    os.system('cls' if os.name == 'nt' else 'clear')
        
    print(f"\n{Fore.WHITE}Pilih metode input:{Style.RESET_ALL}")
    print(f"  {Fore.CYAN}[1]{Style.RESET_ALL} {Fore.GREEN}Scan dari file list IP{Style.RESET_ALL}")
    print(f"  {Fore.CYAN}[2]{Style.RESET_ALL} {Fore.GREEN}Scan dengan RNG IP{Style.RESET_ALL}")
    
    choice = input(f"\n{Fore.YELLOW}➜ Pilihan (1/2): {Style.RESET_ALL}").strip()
    
    scanner = MovableTypeScanner(max_threads=50, max_valid_rng=50)
    
    if choice == '1':
        filename = input(f"{Fore.YELLOW}➜ Masukkan nama file list IP: {Style.RESET_ALL}").strip()
        if filename:
            scanner.scan_from_file(filename)
    elif choice == '2':
        base_ip = input(f"{Fore.YELLOW}➜ Masukkan base IP (contoh: 157.7.44): {Style.RESET_ALL}").strip()
        if base_ip:
            if base_ip.count('.') == 2:
                base_ip = base_ip + '.1'
            
            try:
                max_valid = input(f"{Fore.YELLOW}➜ Jumlah IP valid (default 50): {Style.RESET_ALL}").strip()
                if max_valid:
                    scanner.max_valid_rng = int(max_valid)
            except:
                pass
            
            scanner.scan_random_ips(base_ip)
    else:
        print(f"{Fore.RED}✗ Pilihan tidak valid!{Style.RESET_ALL}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}\n⚠ Scan dihentikan oleh user{Style.RESET_ALL}")
    except Exception as e:
        print(f"{Fore.RED}\n✗ Error: {str(e)}{Style.RESET_ALL}")