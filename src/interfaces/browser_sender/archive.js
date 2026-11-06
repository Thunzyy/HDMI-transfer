// Minimal offline ZIP writer: deflate via CompressionStream when it helps, store otherwise.
const zipArchive = (() => {
  const encoder = new TextEncoder();
  const table = new Uint32Array(256);
  for (let i = 0; i < 256; i++) {
    let c = i;
    for (let j = 0; j < 8; j++) c = (c & 1) ? ((c >>> 1) ^ 0xEDB88320) : (c >>> 1);
    table[i] = c >>> 0;
  }
  function crc32(bytes) {
    let crc = 0xFFFFFFFF;
    for (let i = 0; i < bytes.length; i++) crc = table[(crc ^ bytes[i]) & 0xFF] ^ (crc >>> 8);
    return (crc ^ 0xFFFFFFFF) >>> 0;
  }
  function dosDateTime(ms) {
    const d = new Date(ms || Date.now());
    const year = Math.max(d.getFullYear(), 1980);
    return {
      time: (d.getHours() << 11) | (d.getMinutes() << 5) | (d.getSeconds() >> 1),
      date: ((year - 1980) << 9) | ((d.getMonth() + 1) << 5) | d.getDate(),
    };
  }
  async function deflate(bytes) {
    if (typeof CompressionStream !== "function" || bytes.length === 0) return null;
    try {
      const stream = new Blob([bytes]).stream().pipeThrough(new CompressionStream("deflate-raw"));
      return new Uint8Array(await new Response(stream).arrayBuffer());
    } catch {
      return null;
    }
  }

  // entries: [{ path, file?: Blob, lastModified? }]; paths ending in "/" are directories.
  async function build(entries) {
    if (entries.length > 0xFFFF) throw new Error("Too many files to zip (max 65535)");
    const parts = [];
    const central = [];
    let offset = 0;
    for (const entry of entries) {
      const name = encoder.encode(entry.path);
      const raw = entry.file ? new Uint8Array(await entry.file.arrayBuffer()) : new Uint8Array(0);
      const packed = await deflate(raw);
      const useDeflate = packed !== null && packed.length < raw.length;
      const data = useDeflate ? packed : raw;
      if (offset + data.length > 0xFFFFFFFF) throw new Error("Folder too large to zip (max 4 GiB)");
      const crc = crc32(raw);
      const { time, date } = dosDateTime(entry.lastModified);

      const local = new DataView(new ArrayBuffer(30));
      local.setUint32(0, 0x04034B50, true);
      local.setUint16(4, 20, true);
      local.setUint16(6, 0x0800, true);
      local.setUint16(8, useDeflate ? 8 : 0, true);
      local.setUint16(10, time, true);
      local.setUint16(12, date, true);
      local.setUint32(14, crc, true);
      local.setUint32(18, data.length, true);
      local.setUint32(22, raw.length, true);
      local.setUint16(26, name.length, true);

      const header = new DataView(new ArrayBuffer(46));
      header.setUint32(0, 0x02014B50, true);
      header.setUint16(4, 20, true);
      header.setUint16(6, 20, true);
      header.setUint16(8, 0x0800, true);
      header.setUint16(10, useDeflate ? 8 : 0, true);
      header.setUint16(12, time, true);
      header.setUint16(14, date, true);
      header.setUint32(16, crc, true);
      header.setUint32(20, data.length, true);
      header.setUint32(24, raw.length, true);
      header.setUint16(28, name.length, true);
      header.setUint32(38, entry.path.endsWith("/") ? 0x10 : 0, true);
      header.setUint32(42, offset, true);

      parts.push(new Uint8Array(local.buffer), name, data);
      central.push(new Uint8Array(header.buffer), name);
      offset += 30 + name.length + data.length;
    }
    const centralSize = central.reduce((n, p) => n + p.length, 0);
    const end = new DataView(new ArrayBuffer(22));
    end.setUint32(0, 0x06054B50, true);
    end.setUint16(8, entries.length, true);
    end.setUint16(10, entries.length, true);
    end.setUint32(12, centralSize, true);
    end.setUint32(16, offset, true);
    return new Uint8Array(await new Blob([...parts, ...central, new Uint8Array(end.buffer)]).arrayBuffer());
  }

  function readDirectory(dirEntry) {
    const reader = dirEntry.createReader();
    return new Promise((resolve, reject) => {
      const all = [];
      const next = () => reader.readEntries((batch) => {
        if (!batch.length) resolve(all);
        else { all.push(...batch); next(); }
      }, reject);
      next();
    });
  }
  function entryFile(fileEntry) {
    return new Promise((resolve, reject) => fileEntry.file(resolve, reject));
  }

  // Walk dropped FileSystemEntry items into zip entries, keeping empty folders.
  async function collectDropped(fsEntries) {
    const out = [];
    async function walk(entry, prefix) {
      if (entry.isFile) {
        const file = await entryFile(entry);
        out.push({ path: prefix + entry.name, file, lastModified: file.lastModified });
      } else if (entry.isDirectory) {
        const path = prefix + entry.name + "/";
        const children = await readDirectory(entry);
        if (!children.length) out.push({ path });
        for (const child of children) await walk(child, path);
      }
    }
    for (const entry of fsEntries) await walk(entry, "");
    return out;
  }

  // Files from <input webkitdirectory> or a multi-select carry their relative path.
  function fromFileList(files) {
    return Array.from(files, (file) => ({
      path: file.webkitRelativePath || file.name,
      file,
      lastModified: file.lastModified,
    }));
  }

  return { build, collectDropped, fromFileList };
})();
