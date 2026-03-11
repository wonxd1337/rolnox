#!/usr/bin/env python3
"""
Movable Type Multi Reverse IP Scanner v2.0
- Reverse IP dari multiple sources
- Cari /rsd.xml untuk deteksi Movable Type
- Extract mt-xmlrpc.cgi & mt-upgrade.cgi
- Filter berdasarkan aturan spesifik:
  * XML-RPC: simpan jika HTTP 403, 405, 411
  * Upgrade: simpan jika HTTP 200 (hanya versi 4.x)
- Hapus duplikat
"""

import requests
import argparse
import sys
import time
import re
import socket
import threading
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Set, List, Optional, Dict, Tuple
from datetime import datetime
import urllib3
from urllib.parse import urlparse
import signal

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    MAGENTA = '\033[95m'
    RESET = '\033[0m'
    BOLD = '\033[1m'
    DIM = '\033[2m'

class MTReverseIPScanner:
    def __init__(self, threads: int = 50, timeout: int = 5):
        self.threads = threads
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        
        # Lock untuk threading
        self.lock = threading.Lock()
        
        # Set untuk menyimpan domain yang sudah diproses (menghindari duplikat)
        self.processed_domains = set()
        
        # Hasil
        self.results = {
            'total_ips': 0,
            'total_domains': 0,
            'unique_domains': 0,
            'movable_type_sites': [],      # (domain, version, rsd_url)
            'xmlrpc_urls': [],              # (domain, xmlrpc_url, status_code)
            'upgrade_urls': [],              # (domain, upgrade_url, version, status_code)
            'filtered_xmlrpc': [],           # (domain, xmlrpc_url, status_code) - untuk 403,405,411
            'filtered_upgrade': []            # (domain, upgrade_url, version) - untuk versi 4.x dengan HTTP 200
        }
        
        signal.signal(signal.SIGINT, self.signal_handler)
    
    def signal_handler(self, sig, frame):
        print(f"\n{Colors.YELLOW}[!] Interrupt received, menyimpan hasil...{Colors.RESET}")
        self.save_results()
        self.print_summary()
        sys.exit(0)
    
    def print_banner(self):
        banner = f"""
{Colors.CYAN}╔══════════════════════════════════════════════════════════════╗
║     Movable Type Multi Reverse IP Scanner v2.0            ║
║     Filter: XML-RPC(403/405/411) | Upgrade(200, v4.x)     ║
╚══════════════════════════════════════════════════════════════╝{Colors.RESET}
        """
        print(banner)
    
    def get_base_url(self, url: str) -> str:
        """Mendapatkan base URL"""
        if not url.startswith(('http://', 'https://')):
            url = 'http://' + url
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}"
    
    def is_valid_ip(self, ip: str) -> bool:
        """Validasi IP address"""
        return bool(re.match(r'^\d+\.\d+\.\d+\.\d+$', ip))
    
    # ============ REVERSE IP FUNCTIONS ============
    
    def reverse_ip_hackertarget(self, ip: str) -> Set[str]:
        """Reverse IP via hackertarget.com"""
        domains = set()
        try:
            url = f"https://api.hackertarget.com/reverseiplookup/?q={ip}"
            resp = self.session.get(url, timeout=self.timeout)
            
            if resp.status_code == 200:
                for line in resp.text.split('\n'):
                    line = line.strip()
                    if line and '.' in line and ' ' not in line and 'error' not in line.lower():
                        domains.add(line.lower())
        except Exception as e:
            pass
        return domains
    
    def reverse_ip_yougetsignal(self, ip: str) -> Set[str]:
        """Reverse IP via yougetsignal.com"""
        domains = set()
        try:
            url = "https://domains.yougetsignal.com/domains.php"
            data = {'remoteAddress': ip, 'key': ''}
            headers = {
                'User-Agent': 'Mozilla/5.0',
                'Content-Type': 'application/x-www-form-urlencoded',
                'Referer': 'https://www.yougetsignal.com/tools/web-sites-on-web-server/'
            }
            
            resp = self.session.post(url, data=data, headers=headers, timeout=self.timeout)
            
            if resp.status_code == 200:
                try:
                    result = resp.json()
                    if result.get('status') == 'Success':
                        for domain in result.get('DomainArray', []):
                            if domain and len(domain) >= 2:
                                domains.add(domain[0].lower())
                except:
                    pass
        except Exception as e:
            pass
        return domains
    
    def reverse_ip_ipapi(self, ip: str) -> Set[str]:
        """Reverse IP via ip-api.com"""
        domains = set()
        try:
            url = f"http://ip-api.com/json/{ip}?fields=status,reverse,query"
            resp = self.session.get(url, timeout=self.timeout)
            
            if resp.status_code == 200:
                data = resp.json()
                if data.get('status') == 'success' and data.get('reverse'):
                    reverse = data.get('reverse')
                    if reverse and '.' in reverse:
                        domains.add(reverse.lower())
        except Exception as e:
            pass
        return domains
    
    def get_domains_from_ip(self, ip: str) -> Set[str]:
        """Mengumpulkan domain dari semua sumber reverse IP"""
        all_domains = set()
        
        print(f"{Colors.CYAN}    [Reverse IP] Mengumpulkan domain...{Colors.RESET}")
        
        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {
                executor.submit(self.reverse_ip_hackertarget, ip): 'hackertarget',
                executor.submit(self.reverse_ip_yougetsignal, ip): 'yougetsignal',
                executor.submit(self.reverse_ip_ipapi, ip): 'ipapi'
            }
            
            for future in as_completed(futures):
                source = futures[future]
                try:
                    domains = future.result(timeout=self.timeout + 2)
                    if domains:
                        all_domains.update(domains)
                        print(f"{Colors.GREEN}      [{source}] Found {len(domains)} domains{Colors.RESET}")
                except Exception as e:
                    print(f"{Colors.RED}      [{source}] Error: {str(e)[:30]}{Colors.RESET}")
        
        return all_domains
    
    # ============ RSD.XML FUNCTIONS ============
    
    def check_rsd(self, domain: str) -> Tuple[bool, str, str, str]:
        """
        Cek rsd.xml di /rsd.xml
        Returns: (found, rsd_url, xmlrpc_url, version)
        """
        base = self.get_base_url(domain)
        rsd_url = base + "/rsd.xml"
        
        try:
            resp = self.session.get(rsd_url, timeout=self.timeout, verify=False)
            
            if resp.status_code == 200 and '<rsd' in resp.text and '<api' in resp.text:
                xmlrpc_url = self.extract_xmlrpc_from_rsd(resp.text)
                if xmlrpc_url:
                    version = self.extract_version(resp.text)
                    return True, rsd_url, xmlrpc_url, version
        except:
            pass
        
        return False, None, None, None
    
    def extract_xmlrpc_from_rsd(self, rsd_content: str) -> Optional[str]:
        """Ekstrak URL mt-xmlrpc.cgi dari rsd.xml"""
        # Cari MetaWeblog API
        meta_pattern = r'<api[^>]*name=["\']MetaWeblog["\'][^>]*apiLink=["\']([^"\']+)["\']'
        meta_match = re.search(meta_pattern, rsd_content, re.I)
        if meta_match:
            return meta_match.group(1)
        
        # Fallback: MovableType API
        mt_pattern = r'<api[^>]*name=["\']MovableType["\'][^>]*apiLink=["\']([^"\']+)["\']'
        mt_match = re.search(mt_pattern, rsd_content, re.I)
        if mt_match:
            return mt_match.group(1)
        
        return None
    
    def extract_version(self, rsd_content: str) -> str:
        """Ekstrak version dari rsd.xml"""
        engine_match = re.search(r'<engineName>([^<]+)</engineName>', rsd_content, re.I)
        if engine_match:
            engine = engine_match.group(1)
            ver_match = re.search(r'(\d+\.\d+(?:\.\d+)?)', engine)
            if ver_match:
                return ver_match.group(1)
        return "Unknown"
    
    def is_version_4(self, version: str) -> bool:
        """Cek apakah versi 4.x"""
        return version.startswith('4.') if version != "Unknown" else False
    
    def get_upgrade_url(self, xmlrpc_url: str) -> str:
        """Generate mt-upgrade.cgi URL dengan replace"""
        return xmlrpc_url.replace('mt-xmlrpc.cgi', 'mt-upgrade.cgi')
    
    def check_url_status(self, url: str) -> int:
        """Cek status code URL dengan HEAD request"""
        try:
            resp = self.session.head(url, timeout=self.timeout, verify=False, allow_redirects=True)
            return resp.status_code
        except:
            return 0
    
    # ============ PROCESSING FUNCTIONS ============
    
    def process_domain(self, domain: str, source_ip: str = ""):
        """Process satu domain untuk deteksi Movable Type"""
        
        # Cek duplikat
        if domain in self.processed_domains:
            return
        
        with self.lock:
            self.processed_domains.add(domain)
            self.results['total_domains'] += 1
        
        # Cek rsd.xml
        found, rsd_url, xmlrpc_url, version = self.check_rsd(domain)
        
        if not found:
            return
        
        # Movable Type ditemukan
        print(f"{Colors.GREEN}  ✓ {domain} - MT v{version}{Colors.RESET}")
        
        with self.lock:
            self.results['movable_type_sites'].append((domain, version, rsd_url))
        
        # ============ XML-RPC PROCESSING ============
        if xmlrpc_url:
            status = self.check_url_status(xmlrpc_url)
            print(f"{Colors.DIM}    XML-RPC: {xmlrpc_url} [HTTP {status}]{Colors.RESET}")
            
            with self.lock:
                self.results['xmlrpc_urls'].append((domain, xmlrpc_url, status))
            
            # FILTER XML-RPC: Simpan hanya jika status 403, 405, 411
            if status in [403, 405, 411]:
                print(f"{Colors.YELLOW}      → FILTERED (XML-RPC {status}){Colors.RESET}")
                with self.lock:
                    self.results['filtered_xmlrpc'].append((domain, xmlrpc_url, status))
        
        # ============ UPGRADE PROCESSING ============
        # Upgrade hanya untuk versi 4.x
        if self.is_version_4(version) and xmlrpc_url:
            upgrade_url = self.get_upgrade_url(xmlrpc_url)
            upgrade_status = self.check_url_status(upgrade_url)
            print(f"{Colors.DIM}    Upgrade: {upgrade_url} [HTTP {upgrade_status}]{Colors.RESET}")
            
            with self.lock:
                self.results['upgrade_urls'].append((domain, upgrade_url, version, upgrade_status))
            
            # FILTER UPGRADE: Simpan hanya jika HTTP 200
            if upgrade_status == 200:
                print(f"{Colors.GREEN}      → FILTERED (Upgrade 200 - v{version}){Colors.RESET}")
                with self.lock:
                    self.results['filtered_upgrade'].append((domain, upgrade_url, version))
    
    def process_ip(self, ip: str):
        """Process satu IP address"""
        with self.lock:
            self.results['total_ips'] += 1
            current = self.results['total_ips']
        
        print(f"\n{Colors.CYAN}[{current}] Scanning IP: {ip}{Colors.RESET}")
        
        # Reverse IP dari multiple sources
        domains = self.get_domains_from_ip(ip)
        
        if not domains:
            print(f"{Colors.YELLOW}    No domains found for this IP{Colors.RESET}")
            return
        
        print(f"{Colors.GREEN}    Total unique domains: {len(domains)}{Colors.RESET}")
        
        # Process setiap domain
        for domain in domains:
            self.process_domain(domain, ip)
    
    def scan_ips(self, ips: List[str]):
        """Scan multiple IPs"""
        print(f"\n{Colors.BOLD}[+] Memulai scan {len(ips)} IP addresses{Colors.RESET}")
        print(f"[+] Threads: {self.threads}")
        print(f"[+] Timeout: {self.timeout}s\n")
        
        with ThreadPoolExecutor(max_workers=self.threads) as executor:
            futures = {executor.submit(self.process_ip, ip): ip for ip in ips}
            
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    ip = futures[future]
                    print(f"{Colors.RED}[!] Error scanning {ip}: {str(e)[:50]}{Colors.RESET}")
    
    # ============ OUTPUT FUNCTIONS ============
    
    def save_results(self):
        """Simpan hasil ke file"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"mt_reverse_ip_{timestamp}.txt"
        
        with open(filename, 'w') as f:
            f.write("="*80 + "\n")
            f.write("MOVABLE TYPE REVERSE IP SCAN RESULTS\n")
            f.write(f"Generated: {datetime.now()}\n")
            f.write(f"Total IPs Scanned: {self.results['total_ips']}\n")
            f.write(f"Total Domains Found: {self.results['total_domains']}\n")
            f.write(f"Unique Domains: {len(self.processed_domains)}\n")
            f.write("="*80 + "\n\n")
            
            # 1. FILTERED XML-RPC URLS (403,405,411)
            if self.results['filtered_xmlrpc']:
                f.write("\n[!] XML-RPC URLS (HTTP 403/405/411) [!]\n")
                f.write("-"*60 + "\n")
                for domain, url, status in self.results['filtered_xmlrpc']:
                    f.write(f"Domain : {domain}\n")
                    f.write(f"Status : HTTP {status}\n")
                    f.write(f"URL    : {url}\n")
                    f.write("-"*40 + "\n")
            
            # 2. FILTERED UPGRADE URLS (HTTP 200, Versi 4.x)
            if self.results['filtered_upgrade']:
                f.write("\n[!] UPGRADE URLS (HTTP 200, Versi 4.x) [!]\n")
                f.write("-"*60 + "\n")
                for domain, url, version in self.results['filtered_upgrade']:
                    f.write(f"Domain  : {domain}\n")
                    f.write(f"Version : {version}\n")
                    f.write(f"URL     : {url}\n")
                    f.write("-"*40 + "\n")
            
            # 3. SEMUA SITE MOVABLE TYPE
            if self.results['movable_type_sites']:
                f.write("\n[+] SEMUA SITE MOVABLE TYPE DITEMUKAN [+]\n")
                f.write("-"*60 + "\n")
                for domain, version, rsd_url in self.results['movable_type_sites']:
                    f.write(f"Domain  : {domain}\n")
                    f.write(f"Version : {version}\n")
                    f.write(f"RSD     : {rsd_url}\n")
                    f.write("-"*40 + "\n")
        
        print(f"\n{Colors.GREEN}[✓] Hasil disimpan di: {filename}{Colors.RESET}")
        
        # Juga simpan list sederhana untuk langsung digunakan
        self.save_filtered_lists(timestamp)
    
    def save_filtered_lists(self, timestamp: str):
        """Simpan list filtered URLs ke file terpisah untuk langsung digunakan"""
        
        # XML-RPC list (403,405,411)
        if self.results['filtered_xmlrpc']:
            xmlrpc_file = f"xmlrpc_filtered_{timestamp}.txt"
            with open(xmlrpc_file, 'w') as f:
                for domain, url, status in self.results['filtered_xmlrpc']:
                    f.write(f"{url}\n")
            print(f"{Colors.GREEN}[✓] XML-RPC list: {xmlrpc_file} ({len(self.results['filtered_xmlrpc'])} URLs){Colors.RESET}")
        
        # Upgrade list (HTTP 200, v4.x)
        if self.results['filtered_upgrade']:
            upgrade_file = f"upgrade_filtered_{timestamp}.txt"
            with open(upgrade_file, 'w') as f:
                for domain, url, version in self.results['filtered_upgrade']:
                    f.write(f"{url}\n")
            print(f"{Colors.GREEN}[✓] Upgrade list: {upgrade_file} ({len(self.results['filtered_upgrade'])} URLs){Colors.RESET}")
    
    def print_summary(self):
        """Print ringkasan hasil"""
        print(f"\n{Colors.BOLD}{'='*60}{Colors.RESET}")
        print(f"{Colors.BOLD}SUMMARY{Colors.RESET}")
        print(f"{Colors.BOLD}{'='*60}{Colors.RESET}")
        print(f"Total IPs Scanned      : {self.results['total_ips']}")
        print(f"Total Domains Found    : {self.results['total_domains']}")
        print(f"Unique Domains         : {len(self.processed_domains)}")
        print(f"MT Sites Found         : {len(self.results['movable_type_sites'])}")
        print(f"\n{Colors.YELLOW}FILTERED RESULTS:{Colors.RESET}")
        print(f"XML-RPC (403/405/411)  : {len(self.results['filtered_xmlrpc'])}")
        print(f"Upgrade (200, v4.x)    : {len(self.results['filtered_upgrade'])}")
        print(f"{Colors.BOLD}{'='*60}{Colors.RESET}")

def load_ips(file_path: str) -> List[str]:
    """Load IPs dari file"""
    ips = []
    try:
        with open(file_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    # Validasi IP sederhana
                    if re.match(r'^\d+\.\d+\.\d+\.\d+$', line):
                        ips.append(line)
        print(f"{Colors.GREEN}[+] Loaded {len(ips)} IPs from {file_path}{Colors.RESET}")
    except Exception as e:
        print(f"{Colors.RED}[!] Error loading file: {e}{Colors.RESET}")
        sys.exit(1)
    return ips

def main():
    parser = argparse.ArgumentParser(description='Movable Type Multi Reverse IP Scanner v2.0')
    parser.add_argument('-f', '--file', required=True, help='File berisi daftar IP')
    parser.add_argument('-t', '--threads', type=int, default=50, help='Jumlah thread (default: 50)')
    parser.add_argument('--timeout', type=int, default=5, help='Timeout per request (default: 5)')
    
    args = parser.parse_args()
    
    scanner = MTReverseIPScanner(
        threads=args.threads,
        timeout=args.timeout
    )
    
    scanner.print_banner()
    
    ips = load_ips(args.file)
    if not ips:
        print(f"{Colors.RED}[!] No valid IPs loaded{Colors.RESET}")
        sys.exit(1)
    
    start_time = time.time()
    scanner.scan_ips(ips)
    elapsed_time = time.time() - start_time
    
    scanner.save_results()
    scanner.print_summary()
    
    print(f"\n{Colors.GREEN}[✓] Scan selesai dalam {elapsed_time:.2f} detik{Colors.RESET}")

if __name__ == "__main__":
    main()
