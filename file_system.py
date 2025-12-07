#!/usr/bin/env python3

import os
import json
import math

# ----------------------------
# Quick testing checklist
# ----------------------------
# Run:
#   python3 filesystem.py
#
# 1) Directory basics:
#   mkdir docs
#   ls
#   cd docs
#   ls
#   cd /
#
# 2) Create + open + write + close + reopen + read:
#   create notes.txt
#   open notes.txt
#   write notes.txt "hello from the RAM disk"
#   close notes.txt
#   open notes.txt
#   read notes.txt
#
# 3) Search:
#   search notes.txt
#
# 4) Move/rename:
#   mv notes.txt ideas.txt
#   search ideas.txt
#
# 5) Delete file:
#   delete ideas.txt
#   ls
#
# 6) Delete empty directory:
#   delete docs
#
# ----------------------------

DISK_FILE = "virtual_disk.bin"
META_FILE = "metadata.json"

DISK_SIZE = 1024 * 1024   # 1 MB RAM disk
BLOCK_SIZE = 512
NUM_BLOCKS = DISK_SIZE // BLOCK_SIZE


class FileSystem:
    def __init__(self):
        self.root = {"name": "/", "type": "dir", "children": {}}
        self.current_path = []

        self.free_map = [True] * NUM_BLOCKS
        self.fat = [-2] * NUM_BLOCKS  # -2 free, -1 EOF

        self.open_file_table = {}

        # RAM-backed disk space
        self._disk_mem = bytearray(DISK_SIZE)

    # ---------- startup / save ----------

    def init_filesystem(self):
        """Load previous state if present; otherwise start fresh."""
        self._load_disk_image_if_exists()

        if os.path.exists(META_FILE):
            self._load_metadata()
        else:
            self._reset_fresh_state()
            self._save_state()

        print("File system initialized (RAM disk).")

    def shutdown(self):
        """Final save on exit."""
        self._save_state()

    def _reset_fresh_state(self):
        """Reset to a brand-new empty filesystem."""
        self.root = {"name": "/", "type": "dir", "children": {}}
        self.current_path = []
        self.free_map = [True] * NUM_BLOCKS
        self.fat = [-2] * NUM_BLOCKS
        self.open_file_table = {}
        self._disk_mem = bytearray(DISK_SIZE)

    def _save_state(self):
        """Save metadata + RAM snapshot."""
        self._save_metadata()
        self._save_disk_image()

    def _save_metadata(self):
        """Save directory tree + FAT + free map."""
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
        """Load directory tree + FAT + free map."""
        with open(META_FILE, "r", encoding="utf-8") as f:
            meta = json.load(f)

        if meta.get("block_size") != BLOCK_SIZE:
            raise ValueError("Block size mismatch with metadata.")

        self.root = meta.get("root", {"name": "/", "type": "dir", "children": {}})
        self.free_map = meta.get("free_map", [True] * NUM_BLOCKS)
        self.fat = meta.get("fat", [-2] * NUM_BLOCKS)

    def _save_disk_image(self):
        """Snapshot the RAM disk for persistence."""
        with open(DISK_FILE, "wb") as f:
            f.write(self._disk_mem)

    def _load_disk_image_if_exists(self):
        """Load the last RAM snapshot if present."""
        if not os.path.exists(DISK_FILE):
            self._disk_mem = bytearray(DISK_SIZE)
            return

        with open(DISK_FILE, "rb") as f:
            data = f.read()

        if len(data) < DISK_SIZE:
            data += b"\x00" * (DISK_SIZE - len(data))
        else:
            data = data[:DISK_SIZE]

        self._disk_mem = bytearray(data)

    # ---------- path helpers ----------

    def _get_current_dir_node(self):
        """Return the directory node for the current working directory."""
        node = self.root
        for part in self.current_path:
            node = node["children"][part]
        return node

    def _resolve_path(self, path):
        """Lightweight path resolver mainly used by mv."""
        parts = path.strip("/").split("/") if path != "/" else []

        if path.startswith("/"):
            node = self.root
            if not parts:
                return None, "/"
        else:
            node = self._get_current_dir_node()
            if path == "" or path == ".":
                return None, "."

        for part in parts[:-1]:
            if part in node["children"] and node["children"][part]["type"] == "dir":
                node = node["children"][part]
            else:
                return None, None

        target_name = parts[-1] if parts else ""
        return node, target_name

    # ---------- block + FAT helpers ----------

    def _allocate_blocks(self, n):
        """Allocate n free blocks and link them in the FAT."""
        free_indices = [i for i, ok in enumerate(self.free_map) if ok]
        if len(free_indices) < n:
            return None

        allocated = free_indices[:n]

        for idx in allocated:
            self.free_map[idx] = False
            self.fat[idx] = -1

        for i in range(len(allocated) - 1):
            self.fat[allocated[i]] = allocated[i + 1]

        return allocated

    def _extend_chain(self, first_block, num_new_blocks):
        """Append blocks to an existing file chain."""
        new_blocks = self._allocate_blocks(num_new_blocks)
        if not new_blocks:
            return None

        if first_block == -1:
            return new_blocks[0]

        curr = first_block
        while self.fat[curr] != -1:
            curr = self.fat[curr]

        self.fat[curr] = new_blocks[0]
        return first_block

    def _get_block_chain(self, first_block):
        """Return a list of blocks for a file by following the FAT."""
        chain = []
        b = first_block
        while b != -1 and b != -2:
            chain.append(b)
            b = self.fat[b]
        return chain

    def _free_chain(self, first_block):
        """Free all blocks used by a file."""
        b = first_block
        while b != -1:
            nxt = self.fat[b]
            self.free_map[b] = True
            self.fat[b] = -2
            self._write_block(b, b"")
            b = nxt

    def _write_block(self, block_index, data):
        """Write one block worth of bytes into RAM."""
        start = block_index * BLOCK_SIZE
        block_data = data[:BLOCK_SIZE].ljust(BLOCK_SIZE, b"\x00")
        self._disk_mem[start:start + BLOCK_SIZE] = block_data

    def _read_block(self, block_index):
        """Read one block worth of bytes from RAM."""
        start = block_index * BLOCK_SIZE
        return bytes(self._disk_mem[start:start + BLOCK_SIZE])

    # ---------- user operations ----------

    def mkdir(self, dirname):
        """Create a new directory in the current directory."""
        parent = self._get_current_dir_node()
        if dirname in parent["children"]:
            print(f"Error: '{dirname}' already exists.")
            return

        parent["children"][dirname] = {
            "name": dirname,
            "type": "dir",
            "children": {}
        }
        self._save_state()
        print(f"Directory '{dirname}' created.")

    def cd(self, dirname):
        """Change current directory."""
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
        """List contents of the current directory."""
        node = self._get_current_dir_node()
        path_str = "/" + "/".join(self.current_path)
        print(f"Contents of {path_str if path_str != '/' else '/'}:")
        for name, entry in node["children"].items():
            if entry["type"] == "dir":
                print(f"  [DIR]  {name}")
            else:
                print(f"  [FILE] {name} (Size: {entry['size']})")

    def create_file(self, filename):
        """Create a new empty file."""
        parent = self._get_current_dir_node()
        if filename in parent["children"]:
            print(f"Error: '{filename}' already exists.")
            return

        parent["children"][filename] = {
            "name": filename,
            "type": "file",
            "size": 0,
            "first_block": -1
        }
        self._save_state()
        print(f"File '{filename}' created.")

    def open_file(self, filename):
        """Open a file so read/write are allowed."""
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
        """Close an open file."""
        if filename in self.open_file_table:
            del self.open_file_table[filename]
            print(f"File '{filename}' closed.")
        else:
            print(f"Error: File '{filename}' not open.")

    def write_file(self, filename, data):
        """Overwrite a file with new content (grows blocks if needed)."""
        if filename not in self.open_file_table:
            print("Error: File not open.")
            return

        entry = self.open_file_table[filename]["node"]
        data_bytes = data.encode("utf-8")
        total_len = len(data_bytes)

        blocks_needed = math.ceil(total_len / BLOCK_SIZE)
        if blocks_needed == 0:
            blocks_needed = 1

        current_chain = self._get_block_chain(entry["first_block"])
        current_count = len(current_chain)

        if blocks_needed > current_count:
            needed = blocks_needed - current_count
            new_start = self._extend_chain(entry["first_block"], needed)
            if new_start is None:
                print("Error: Disk full.")
                return
            if entry["first_block"] == -1:
                entry["first_block"] = new_start
            current_chain = self._get_block_chain(entry["first_block"])

        offset = 0
        remaining = total_len

        for b in current_chain:
            if remaining <= 0:
                self._write_block(b, b"")
                continue

            chunk = data_bytes[offset: offset + BLOCK_SIZE]
            self._write_block(b, chunk)
            offset += len(chunk)
            remaining -= len(chunk)

        entry["size"] = total_len
        self._save_state()
        print(f"Wrote {total_len} bytes to '{filename}'.")

    def read_file(self, filename):
        """Read and print file contents."""
        if filename not in self.open_file_table:
            print("Error: File not open.")
            return

        entry = self.open_file_table[filename]["node"]
        if entry["first_block"] == -1 or entry["size"] == 0:
            print("")
            return

        chain = self._get_block_chain(entry["first_block"])
        bytes_to_read = entry["size"]
        out = b""

        for b in chain:
            if bytes_to_read <= 0:
                break
            chunk = self._read_block(b)
            take = min(BLOCK_SIZE, bytes_to_read)
            out += chunk[:take]
            bytes_to_read -= take

        print(out.decode("utf-8", errors="replace"))

    def delete_file(self, name):
        """Delete a file or an empty directory."""
        parent = self._get_current_dir_node()
        if name not in parent["children"]:
            print("Not found.")
            return

        entry = parent["children"][name]

        if entry["type"] == "dir":
            if entry["children"]:
                print("Error: Directory not empty.")
                return
        else:
            if entry["first_block"] != -1:
                self._free_chain(entry["first_block"])

        parent["children"].pop(name, None)
        self.open_file_table.pop(name, None)

        self._save_state()
        print(f"Deleted '{name}'.")

    def mv(self, src_path, dest_path):
        """Move or rename a file/directory."""
        src_parent, src_name = self._resolve_path(src_path)
        if src_parent is None or src_name not in src_parent["children"]:
            print(f"Error: Source '{src_path}' not found.")
            return

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

        entry = src_parent["children"].pop(src_name)
        entry["name"] = target_name
        target_dir["children"][target_name] = entry

        if src_name in self.open_file_table:
            del self.open_file_table[src_name]
            print(f"Note: '{src_name}' was open and got closed due to move/rename.")

        self._save_state()
        print(f"Moved '{src_path}' to '{target_name}'")

    def search_files(self, name):
        """Search the whole filesystem for a matching name."""
        matches = []

        def dfs(node, path_so_far):
            if node["type"] != "dir":
                return
            for child_name, child in node["children"].items():
                child_path = f"{path_so_far}/{child_name}" if path_so_far != "/" else f"/{child_name}"
                if child_name == name:
                    matches.append((child_path, child["type"]))
                if child["type"] == "dir":
                    dfs(child, child_path)

        dfs(self.root, "/")

        if not matches:
            print(f"No matches found for '{name}'.")
            return

        print(f"Matches for '{name}':")
        for p, t in matches:
            print(f"  [{'FILE' if t == 'file' else 'DIR'}] {p}")


def main():
    fs = FileSystem()
    fs.init_filesystem()

    print("\nRAM-Disk File System")
    print("Commands: mkdir, cd, ls, create, open, write, read, close, delete, mv, search, exit")
    print('Tip: Use quotes for write, e.g. write notes.txt "hello world"')

    while True:
        try:
            prompt_path = "/" + "/".join(fs.current_path)
            raw = input(f"{prompt_path if prompt_path != '/' else '/'}> ").strip()
        except EOFError:
            break

        if not raw:
            continue

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
            content = raw[raw.index(filename) + len(filename):].strip().strip('"')
            fs.write_file(filename, content)
        elif cmd == "read" and len(parts) == 2:
            fs.read_file(parts[1])
        elif cmd == "delete" and len(parts) == 2:
            fs.delete_file(parts[1])
        elif cmd == "mv" and len(parts) == 3:
            fs.mv(parts[1], parts[2])
        elif cmd == "search" and len(parts) == 2:
            fs.search_files(parts[1])
        elif cmd == "exit":
            break
        else:
            print("Unknown command or wrong usage.")

    fs.shutdown()
    print("Goodbye!")


if __name__ == "__main__":
    main()
