#!/usr/bin/env python3

import os
import json
import math

DISK_FILE = "virtual_disk.bin"
META_FILE = "metadata.json"

DISK_SIZE = 1024 * 1024  # 1 MB virtual disk
BLOCK_SIZE = 512         # bytes per block
NUM_BLOCKS = DISK_SIZE // BLOCK_SIZE


class FileSystem:
    def __init__(self):
        # Root directory node
        # Structure: { "name": "/", "type": "dir", "children": {} }
        self.root = {"name": "/", "type": "dir", "children": {}}
        
        # Current working directory path (as a list of names, e.g., ['home', 'user'])
        self.current_path = [] 

        # free_map[i] = True means block i is free
        self.free_map = [True] * NUM_BLOCKS
        # fat[i] = index of next block, -1 = EOF, -2 = Free
        self.fat = [-2] * NUM_BLOCKS
        
        # open_file_table: filename -> {"pos": position, "node": file_node}
        self.open_file_table = {}
        self._disk = None

    # ----------------- Initialization & Metadata -----------------

    def init_fileSystem(self):
        if os.path.exists(DISK_FILE) and os.path.exists(META_FILE):
            self._load_metadata()
            self._disk = open(DISK_FILE, "r+b")
        else:
            with open(DISK_FILE, "wb") as f:
                f.truncate(DISK_SIZE)
            
            # Initialize fresh root
            self.root = {"name": "/", "type": "dir", "children": {}}
            self.free_map = [True] * NUM_BLOCKS
            self.fat = [-2] * NUM_BLOCKS
            self.open_file_table = {}
            
            self._save_metadata()
            self._disk = open(DISK_FILE, "r+b")

        print("File system initialized.")

    def _save_metadata(self):
        meta = {
            "block_size": BLOCK_SIZE,
            "num_blocks": NUM_BLOCKS,
            "root": self.root,
            "free_map": self.free_map,
            "fat": self.fat,
        }
        with open(META_FILE, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

    def _load_metadata(self):
        with open(META_FILE, "r", encoding="utf-8") as f:
            meta = json.load(f)

        if meta.get("block_size") != BLOCK_SIZE:
            raise ValueError("Config mismatch.")

        self.root = meta.get("root", {"name": "/", "type": "dir", "children": {}})
        self.free_map = meta.get("free_map", [True] * NUM_BLOCKS)
        self.fat = meta.get("fat", [-2] * NUM_BLOCKS)

    # ----------------- Path & Directory Helpers -----------------

    def _get_current_dir_node(self):
        """Traverse from root to current_path to get the directory node."""
        node = self.root
        for part in self.current_path:
            node = node["children"][part]
        return node

    def _resolve_path(self, path):
        """
        Resolves a path string to (parent_node, target_name).
        Supports absolute ('/a/b') and relative ('b') paths.
        """
        parts = path.strip("/").split("/") if path != "/" else []
        if path.startswith("/"):
            # Absolute path
            node = self.root
            # If path is just "/", parent is None? Or we handle it specifically.
            if not parts:
                return None, "/" 
        else:
            # Relative path: Start from CWD
            node = self._get_current_dir_node()
            if path == "" or path == ".":
                return None, "." # Current dir

        # Traverse all but the last part
        for part in parts[:-1]:
            if part == "..":
                # Go up logic not implemented for simplicity in this specific helper
                # strict traversal for now:
                pass 
            
            if part in node["children"] and node["children"][part]["type"] == "dir":
                node = node["children"][part]
            else:
                return None, None # Invalid path

        target_name = parts[-1] if parts else ""
        return node, target_name

    # ----------------- Low-level Block Helpers -----------------

    def _allocate_blocks(self, num_blocks):
        """Finds num_blocks free blocks. Returns list of indices."""
        free_indices = [i for i, free in enumerate(self.free_map) if free]
        if len(free_indices) < num_blocks:
            return None
        
        allocated = free_indices[:num_blocks]
        for idx in allocated:
            self.free_map[idx] = False
            self.fat[idx] = -1
        
        # Link them locally
        for i in range(len(allocated) - 1):
            self.fat[allocated[i]] = allocated[i+1]
        
        return allocated

    def _extend_chain(self, first_block, num_new_blocks):
        """Allocates new blocks and appends them to the chain ending at 'first_block'."""
        new_blocks = self._allocate_blocks(num_new_blocks)
        if not new_blocks:
            return None

        if first_block == -1:
            # File was empty, this is the new start
            return new_blocks[0]

        # Find end of current chain
        curr = first_block
        while self.fat[curr] != -1:
            curr = self.fat[curr]
        
        # Link old end to new start
        self.fat[curr] = new_blocks[0]
        return first_block

    def _get_block_chain(self, first_block):
        blocks = []
        b = first_block
        while b != -1 and b != -2:
            blocks.append(b)
            b = self.fat[b]
        return blocks

    def _write_block(self, block_index, data):
        self._disk.seek(block_index * BLOCK_SIZE)
        pad = BLOCK_SIZE - len(data)
        self._disk.write(data + b"\x00" * pad)

    def _read_block(self, block_index):
        self._disk.seek(block_index * BLOCK_SIZE)
        return self._disk.read(BLOCK_SIZE)

    # ----------------- Operations -----------------

    def mkdir(self, dirname):
        parent = self._get_current_dir_node()
        if dirname in parent["children"]:
            print(f"Error: '{dirname}' already exists.")
            return
        
        parent["children"][dirname] = {
            "name": dirname,
            "type": "dir",
            "children": {}
        }
        self._save_metadata()
        print(f"Directory '{dirname}' created.")

    def cd(self, dirname):
        if dirname == "..":
            if self.current_path:
                self.current_path.pop()
            return
        
        if dirname == "/":
            self.current_path = []
            return

        parent = self._get_current_dir_node()
        if dirname in parent["children"]:
            entry = parent["children"][dirname]
            if entry["type"] == "dir":
                self.current_path.append(dirname)
            else:
                print(f"Error: '{dirname}' is not a directory.")
        else:
            print(f"Error: Directory '{dirname}' not found.")

    def ls(self):
        node = self._get_current_dir_node()
        print(f"Contents of /{'/'.join(self.current_path)}:")
        for name, entry in node["children"].items():
            if entry["type"] == "dir":
                print(f"  [DIR]  {name}")
            else:
                print(f"  [FILE] {name} (Size: {entry['size']})")

    def create_file(self, filename):
        """Create a new empty file (dynamic size)."""
        parent = self._get_current_dir_node()
        if filename in parent["children"]:
            print(f"Error: '{filename}' already exists.")
            return

        # No blocks allocated initially
        parent["children"][filename] = {
            "name": filename,
            "type": "file",
            "size": 0,
            "first_block": -1 
        }
        self._save_metadata()
        print(f"File '{filename}' created.")

    def open_file(self, filename):
        parent = self._get_current_dir_node()
        if filename not in parent["children"]:
            print(f"Error: File '{filename}' not found.")
            return
        
        entry = parent["children"][filename]
        if entry["type"] != "file":
            print(f"Error: '{filename}' is a directory.")
            return

        if filename in self.open_file_table:
            print(f"File '{filename}' already open.")
            return

        self.open_file_table[filename] = {"pos": 0, "node": entry}
        print(f"File '{filename}' opened.")

    def close_file(self, filename):
        if filename in self.open_file_table:
            del self.open_file_table[filename]
            print(f"File '{filename}' closed.")
        else:
            print(f"Error: File '{filename}' not open.")

    def write_file(self, filename, data):
        if filename not in self.open_file_table:
            print("Error: File not open.")
            return

        entry = self.open_file_table[filename]["node"]
        data_bytes = data.encode("utf-8")
        total_len = len(data_bytes)
        
        # Calculate blocks needed
        blocks_needed = math.ceil(total_len / BLOCK_SIZE)
        if blocks_needed == 0: blocks_needed = 1 # Reserve at least 1 if empty? Or 0.
        
        current_chain = self._get_block_chain(entry["first_block"])
        current_count = len(current_chain)

        # Dynamic Allocation Logic
        if blocks_needed > current_count:
            needed = blocks_needed - current_count
            new_start = self._extend_chain(entry["first_block"], needed)
            if new_start is None:
                print("Error: Disk full.")
                return
            if entry["first_block"] == -1:
                entry["first_block"] = new_start
            
            # Refresh chain
            current_chain = self._get_block_chain(entry["first_block"])

        # Write Data
        offset = 0
        remaining = total_len
        for b in current_chain:
            if remaining <= 0:
                # Zero out rest of allocated blocks if any
                self._write_block(b, b"")
                continue
            
            chunk = data_bytes[offset : offset + BLOCK_SIZE]
            self._write_block(b, chunk)
            offset += len(chunk)
            remaining -= len(chunk)

        entry["size"] = total_len
        self._save_metadata()
        print(f"Wrote {total_len} bytes to '{filename}'.")

    def read_file(self, filename):
        if filename not in self.open_file_table:
            print("Error: File not open.")
            return

        entry = self.open_file_table[filename]["node"]
        if entry["first_block"] == -1:
            print("")
            return

        chain = self._get_block_chain(entry["first_block"])
        data = b""
        bytes_to_read = entry["size"]

        for b in chain:
            if bytes_to_read <= 0: break
            chunk = self._read_block(b)
            take = min(len(chunk), bytes_to_read)
            data += chunk[:take]
            bytes_to_read -= take
        
        print(data.decode("utf-8"))

    def delete_file(self, filename):
        parent = self._get_current_dir_node()
        if filename not in parent["children"]:
            print("Not found.")
            return
        
        entry = parent["children"][filename]
        if entry["type"] == "dir":
            # Simple check: only delete empty dirs
            if entry["children"]:
                print("Error: Directory not empty.")
                return
        else:
            # Free blocks
            if entry["first_block"] != -1:
                # Helper to free chain (simplified logic needed here)
                b = entry["first_block"]
                while b != -1:
                    nxt = self.fat[b]
                    self.free_map[b] = True
                    self.fat[b] = -2
                    b = nxt

        del parent["children"][filename]
        if filename in self.open_file_table:
            del self.open_file_table[filename]
            
        self._save_metadata()
        print(f"Deleted '{filename}'.")

    def mv(self, src_path, dest_path):
        # 1. Source
        src_parent, src_name = self._resolve_path(src_path)
        if src_parent is None or src_name not in src_parent["children"]:
             print(f"Error: Source '{src_path}' not found.")
             return
        
        # 2. Destination
        dest_parent, dest_name = self._resolve_path(dest_path)
        
        target_dir = None
        target_name = None
        
        if dest_parent is None and dest_name == "/":
            target_dir = self.root
            target_name = src_name
        elif dest_parent is None and dest_name == ".":
            target_dir = self._get_current_dir_node()
            target_name = src_name
        elif dest_parent is not None:
            if dest_name in dest_parent["children"]:
                existing = dest_parent["children"][dest_name]
                if existing["type"] == "dir":
                    target_dir = existing
                    target_name = src_name
                else:
                    print(f"Error: Destination '{dest_path}' already exists.")
                    return
            else:
                target_dir = dest_parent
                target_name = dest_name
        else:
             print("Error: Invalid destination.")
             return

        if target_name in target_dir["children"]:
             print(f"Error: Destination '{target_name}' already exists in target.")
             return

        # 3. Execute Move
        entry = src_parent["children"].pop(src_name)
        entry["name"] = target_name
        target_dir["children"][target_name] = entry
        
        # Close if open (simplest handling of handles)
        if src_name in self.open_file_table:
            del self.open_file_table[src_name]
            print(f"Note: File '{src_name}' was open and has been closed.")

        self._save_metadata()
        print(f"Moved '{src_path}' to '{target_name}'")

# ----------------- Main Loop -----------------

def main():
    fs = FileSystem()
    fs.init_fileSystem()
    
    print("Enhanced File System")
    print("Commands: mkdir, cd, ls, create, open, write, read, close, delete, mv, exit")

    while True:
        try:
            raw = input(f"/{'/'.join(fs.current_path)}> ").strip()
        except EOFError: break
        
        if not raw: continue
        parts = raw.split()
        cmd = parts[0].lower()

        if cmd == "mkdir" and len(parts) == 2:
            fs.mkdir(parts[1])
        elif cmd == "cd" and len(parts) == 2:
            fs.cd(parts[1])
        elif cmd == "ls":
            fs.ls()
        elif cmd == "create" and len(parts) == 2:
            fs.create_file(parts[1])
        elif cmd == "open" and len(parts) == 2:
            fs.open_file(parts[1])
        elif cmd == "close" and len(parts) == 2:
            fs.close_file(parts[1])
        elif cmd == "write" and len(parts) >= 3:
            filename = parts[1]
            content = raw[raw.index(filename)+len(filename):].strip().strip('"')
            fs.write_file(filename, content)
        elif cmd == "read" and len(parts) == 2:
            fs.read_file(parts[1])
        elif cmd == "delete" and len(parts) == 2:
            fs.delete_file(parts[1])
        elif cmd == "mv" and len(parts) == 3:
            fs.mv(parts[1], parts[2])
        elif cmd == "exit":
            break
        else:
            print("Unknown command.")

if __name__ == "__main__":
    main()
