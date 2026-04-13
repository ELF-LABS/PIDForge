/**
 * FlightForge MSP bridge — BLE (Nordic UART) or WebSocket simulator fallback.
 */
const NUS_SERVICE = '6e400001-b5a3-f393-e0a9-e50e24dcca9e';
const NUS_RX_CHAR = '6e400002-b5a3-f393-e0a9-e50e24dcca9e';
const NUS_TX_CHAR = '6e400003-b5a3-f393-e0a9-e50e24dcca9e';

const MSP_PID = 112;
const MSP_SET_PID = 202;
const MSP_EEPROM_WRITE = 250;
const MSP_DATAFLASH_SUMMARY = 70;
const MSP_DATAFLASH_READ = 71;
const MSP_STATUS = 101;
const MSP_FC_VARIANT = 2;

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

function crc8MspV1(body) {
  let c = 0;
  for (let i = 0; i < body.length; i++) c ^= body[i];
  return c & 0xff;
}

function encodeMspV1(cmd, payload = []) {
  const pl = payload instanceof Uint8Array ? payload : new Uint8Array(payload);
  const len = pl.length & 0xff;
  const c = cmd & 0xff;
  const head = new Uint8Array([len, c]);
  const body = new Uint8Array(2 + pl.length);
  body.set(head, 0);
  body.set(pl, 2);
  const crc = crc8MspV1(body);
  const out = new Uint8Array(3 + body.length + 1);
  out[0] = 0x24;
  out[1] = 0x4d;
  out[2] = 0x3c;
  out.set(body, 3);
  out[3 + body.length] = crc;
  return out;
}

function parseMspV1Frame(buf) {
  if (buf.length < 6 || buf[0] !== 0x24 || buf[1] !== 0x4d || buf[2] !== 0x3e) return null;
  const size = buf[3];
  const cmd = buf[4];
  if (buf.length < 5 + size + 1) return null;
  const payload = buf.slice(5, 5 + size);
  const crc = buf[5 + size];
  const expect = crc8MspV1(buf.slice(3, 5 + size));
  if (crc !== expect) return null;
  return { cmd, payload };
}

export class BtMspBridge {
  constructor(serverUrl) {
    this.serverUrl = serverUrl || '';
    this.mode = 'ble';
    this.device = null;
    this.bleServer = null;
    this.rxChar = null;
    this.txChar = null;
    this.ws = null;
    this._rxBuf = new Uint8Array(0);
    this._waiters = new Map();
    this.chunkSize = 20;
  }

  async connect() {
    this.mode = 'ble';
    if (!navigator.bluetooth) throw new Error('WebBluetooth not available');
    this.device = await navigator.bluetooth.requestDevice({
      optionalServices: [NUS_SERVICE],
      filters: [{ services: [NUS_SERVICE] }],
    });
    this.bleServer = await this.device.gatt.connect();
    const svc = await this.bleServer.getPrimaryService(NUS_SERVICE);
    this.rxChar = await svc.getCharacteristic(NUS_RX_CHAR);
    this.txChar = await svc.getCharacteristic(NUS_TX_CHAR);
    await this.txChar.startNotifications();
    this.txChar.addEventListener('characteristicvaluechanged', (e) => {
      this._onBytes(new Uint8Array(e.target.value.buffer));
    });
  }

  /**
   * Mock FC (FlightForge simulator) — same MSP v1 frames over WebSocket.
   * @param {string} url e.g. ws://127.0.0.1:5051
   */
  async connectSimulator(url) {
    this.disconnect();
    this.mode = 'simulator';
    const u = url || `ws://${typeof location !== 'undefined' ? location.hostname : '127.0.0.1'}:5051`;
    await new Promise((resolve, reject) => {
      this.ws = new WebSocket(u);
      this.ws.binaryType = 'arraybuffer';
      this.ws.onopen = () => resolve();
      this.ws.onerror = () => reject(new Error(`WebSocket failed: ${u}`));
      this.ws.onmessage = (ev) => {
        if (typeof ev.data === 'string') return;
        this._onBytes(new Uint8Array(ev.data));
      };
    });
  }

  disconnect() {
    try {
      if (this.ws) {
        this.ws.close();
      }
    } catch (_) {}
    this.ws = null;
    try {
      if (this.bleServer && this.bleServer.connected) this.bleServer.disconnect();
    } catch (_) {}
    this.device = null;
    this.bleServer = null;
    this.rxChar = null;
    this.txChar = null;
    this.mode = 'ble';
  }

  _onBytes(chunk) {
    const merged = new Uint8Array(this._rxBuf.length + chunk.length);
    merged.set(this._rxBuf, 0);
    merged.set(chunk, this._rxBuf.length);
    let buf = merged;
    const needle = new Uint8Array([0x24, 0x4d, 0x3e]);
    while (true) {
      const i = this._findSub(buf, needle);
      if (i < 0) {
        this._rxBuf = buf;
        break;
      }
      if (buf.length - i < 5) {
        this._rxBuf = buf.slice(i);
        break;
      }
      const size = buf[i + 3];
      const total = 3 + 1 + 1 + size + 1;
      if (buf.length - i < total) {
        this._rxBuf = buf.slice(i);
        break;
      }
      const frame = buf.slice(i, i + total);
      buf = buf.slice(i + total);
      const parsed = parseMspV1Frame(frame);
      if (!parsed) continue;
      const q = this._waiters.get(parsed.cmd);
      if (q) {
        this._waiters.delete(parsed.cmd);
        q.resolve(parsed.payload);
      }
    }
  }

  _findSub(hay, needle) {
    outer: for (let i = 0; i <= hay.length - needle.length; i++) {
      for (let j = 0; j < needle.length; j++) if (hay[i + j] !== needle[j]) continue outer;
      return i;
    }
    return -1;
  }

  async sendMspCommand(cmd, payload = []) {
    const frame = encodeMspV1(cmd, payload);
    const p = new Promise((resolve, reject) => {
      const to = setTimeout(() => {
        this._waiters.delete(cmd & 0xff);
        reject(new Error('MSP timeout cmd=' + cmd));
      }, 8000);
      this._waiters.set(cmd & 0xff, {
        resolve: (pl) => {
          clearTimeout(to);
          resolve(pl);
        },
      });
    });
    if (this.mode === 'simulator' && this.ws && this.ws.readyState === 1) {
      this.ws.send(frame);
      return p;
    }
    if (!this.rxChar) throw new Error('Not connected');
    for (let i = 0; i < frame.length; i += this.chunkSize) {
      const chunk = frame.slice(i, i + this.chunkSize);
      await this.rxChar.writeValue(chunk);
      await sleep(15);
    }
    return p;
  }

  async readStatus() {
    return this.sendMspCommand(MSP_STATUS);
  }

  async readPids() {
    return this.sendMspCommand(MSP_PID);
  }

  async writePids(pidBytes) {
    await this.sendMspCommand(MSP_SET_PID, pidBytes);
    await this.sendMspCommand(MSP_EEPROM_WRITE);
  }

  async readBoardInfo() {
    return this.sendMspCommand(MSP_FC_VARIANT);
  }

  async dataflashSummary() {
    return this.sendMspCommand(MSP_DATAFLASH_SUMMARY);
  }

  async dataflashRead(address, size) {
    const b = new Uint8Array(4 + 2);
    const view = new DataView(b.buffer);
    view.setUint32(0, address >>> 0, true);
    view.setUint16(4, size & 0xffff, true);
    return this.sendMspCommand(MSP_DATAFLASH_READ, b);
  }

  /** Ask simulator to regenerate synthetic blackbox CSV in RAM. */
  async primeSimBlackbox() {
    if (this.mode !== 'simulator' || !this.ws) throw new Error('simulator only');
    await new Promise((resolve, reject) => {
      const t = setTimeout(() => reject(new Error('SIM:GENERATE timeout')), 5000);
      const onMsg = (ev) => {
        if (typeof ev.data === 'string' && ev.data.startsWith('SIM:OK')) {
          clearTimeout(t);
          this.ws.removeEventListener('message', onMsg);
          resolve();
        }
      };
      this.ws.addEventListener('message', onMsg);
      this.ws.send('SIM:GENERATE');
    });
  }

  async pushCliLines(lines) {
    if (this.mode === 'simulator' && this.ws && this.ws.readyState === 1) {
      const body = lines.map((l) => (l.endsWith('\n') ? l : l + '\n')).join('');
      this.ws.send(`SIM:CLI\n${body}`);
      return;
    }
    const enc = new TextEncoder();
    for (const line of lines) {
      const payload = enc.encode(line.endsWith('\n') ? line : line + '\n');
      for (let i = 0; i < payload.length; i += this.chunkSize) {
        const chunk = payload.slice(i, i + this.chunkSize);
        await this.rxChar.writeValue(chunk);
        await sleep(40);
      }
    }
  }
}
