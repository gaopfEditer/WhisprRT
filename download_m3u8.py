#!/usr/bin/env python3
"""
Download and decrypt HLS (m3u8) video with AES-128 encryption
"""
import os
import re
import urllib.request
import urllib.parse
from pathlib import Path
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

def download_file(url, output_path, headers=None):
    """Download a file with headers"""
    if headers is None:
        headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}
    
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=60) as response:
        data = response.read()
        with open(output_path, 'wb') as f:
            f.write(data)
    return output_path

def decrypt_ts(encrypted_path, decrypted_path, key, iv):
    """Decrypt a TS file using AES-128-CBC"""
    with open(encrypted_path, 'rb') as f:
        encrypted_data = f.read()
    
    cipher = AES.new(key, AES.MODE_CBC, iv=iv)
    decrypted_data = cipher.decrypt(encrypted_data)
    
    # Remove PKCS7 padding
    try:
        decrypted_data = unpad(decrypted_data, AES.block_size)
    except ValueError:
        pass  # May already be unpadded
    
    with open(decrypted_path, 'wb') as f:
        f.write(decrypted_data)

def parse_m3u8(content):
    """Parse m3u8 content and extract segments info"""
    lines = content.strip().split('\n')
    
    key_url = None
    key_iv = None
    segments = []
    
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        
        # Parse key info
        if line.startswith('#EXT-X-KEY'):
            match = re.search(r'URI="([^"]+)"', line)
            if match:
                key_url = match.group(1)
            
            iv_match = re.search(r'IV=0x([0-9a-fA-F]+)', line)
            if iv_match:
                key_iv = bytes.fromhex(iv_match.group(1))
        
        # Parse segment duration and URL
        if line.startswith('#EXTINF:'):
            duration_match = re.search(r'#EXTINF:([\d.]+)', line)
            duration = float(duration_match.group(1)) if duration_match else 0
            
            # Next line should be the URL
            i += 1
            if i < len(lines):
                seg_url = lines[i].strip()
                segments.append({'url': seg_url, 'duration': duration})
        
        i += 1
    
    return key_url, key_iv, segments

def download_m3u8_video(m3u8_url, output_file):
    """Main function to download and merge m3u8 video"""
    print(f"Downloading m3u8: {m3u8_url}")
    
    # Create temp directory
    temp_dir = Path("temp_video_download")
    temp_dir.mkdir(exist_ok=True)
    
    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}
    
    # Download m3u8 content
    req = urllib.request.Request(m3u8_url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as response:
        m3u8_content = response.read().decode('utf-8')
    
    # Parse m3u8
    key_url, key_iv, segments = parse_m3u8(m3u8_content)
    
    print(f"Found {len(segments)} segments")
    print(f"Key URL: {key_url}")
    print(f"IV: {key_iv.hex() if key_iv else 'None'}")
    
    if not segments:
        print("No segments found!")
        return
    
    # Download key
    key_data = None
    if key_url:
        print(f"Downloading key...")
        req = urllib.request.Request(key_url, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as response:
            key_data = response.read()
        print(f"Key size: {len(key_data)} bytes")
    
    # Download and decrypt segments
    segment_files = []
    for i, seg in enumerate(segments):
        seg_url = seg['url']
        print(f"Downloading segment {i+1}/{len(segments)}...")
        
        encrypted_path = temp_dir / f"seg_{i:04d}.ts.enc"
        decrypted_path = temp_dir / f"seg_{i:04d}.ts"
        
        try:
            download_file(seg_url, encrypted_path, headers)
            
            if key_data and key_iv:
                decrypt_ts(encrypted_path, decrypted_path, key_data, key_iv)
                os.remove(encrypted_path)  # Remove encrypted file
                segment_files.append(decrypted_path)
            else:
                segment_files.append(encrypted_path)
        except Exception as e:
            print(f"Error downloading segment {i+1}: {e}")
            continue
    
    # Merge segments using cat command
    print(f"Merging {len(segment_files)} segments...")
    file_list_path = temp_dir / "file_list.txt"
    with open(file_list_path, 'w') as f:
        for seg_file in segment_files:
            f.write(f"file '{seg_file.absolute()}'\n")
    
    # Use ffmpeg to merge if available, otherwise use cat
    import shutil
    if shutil.which('ffmpeg'):
        cmd = f"ffmpeg -f concat -safe 0 -i {file_list_path} -c copy {output_file}"
    else:
        # Simple concatenation
        cmd = f"cat {' '.join(str(f) for f in segment_files)} > {output_file}"
    
    print(f"Running: {cmd}")
    result = os.system(cmd)
    
    if result == 0:
        print(f"✓ Video saved to: {output_file}")
    else:
        print(f"Merge failed with code: {result}")
    
    # Cleanup
    for f in segment_files:
        if f.exists():
            os.remove(f)
    if file_list_path.exists():
        os.remove(file_list_path)
    temp_dir.rmdir()

if __name__ == "__main__":
    M3U8_URL = "https://hls.fqeltl.cn/videos5/1b1e46134825653b43eeeaeaec65894f/1b1e46134825653b43eeeaeaec65894f.m3u8?auth_key=1772367609-69a42ef932c4a-0-38631aadcf12070b27a7b1e99e3e97fb&v=3&time=0"
    OUTPUT_FILE = "video_downloaded.ts"
    
    try:
        from Crypto.Cipher import AES
        download_m3u8_video(M3U8_URL, OUTPUT_FILE)
    except ImportError:
        print("pycryptodome not installed. Installing...")
        import subprocess
        subprocess.run(["pip3", "install", "--user", "pycryptodome"])
        print("Please run the script again after installation.")
