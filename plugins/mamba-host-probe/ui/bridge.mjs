export class HostBridge {
  constructor(surface, timeoutMs = 10000) {
    this.surface = surface;
    this.timeoutMs = timeoutMs;
    this.pending = new Map();
    this.nextId = 0;
    this.closed = false;
    /** @type {(method: string, params?: unknown) => void} */
    this.onnotification = () => {};
    this.receive = (event) => {
      if (event.source !== surface.parent || event.data?.jsonrpc !== '2.0') return;
      const message = event.data;
      if (message.method) {
        if (message.method === 'ping' && message.id !== undefined) {
          surface.parent.postMessage({ jsonrpc: '2.0', id: message.id, result: {} }, '*');
        } else if (message.method === 'ui/resource-teardown') {
          surface.parent.postMessage({ jsonrpc: '2.0', id: message.id, result: {} }, '*');
          this.close();
          this.onnotification(message.method, message.params);
        } else {
          this.onnotification(message.method, message.params);
        }
        return;
      }
      const pending = this.pending.get(message.id);
      if (!pending) return;
      this.pending.delete(message.id);
      clearTimeout(pending.timer);
      if (message.error) pending.reject(new Error(message.error.message || 'Host request failed'));
      else pending.resolve(message.result);
    };
    surface.addEventListener('message', this.receive);
  }

  request(method, params) {
    if (this.closed) return Promise.reject(new Error('Host bridge is closed'));
    return new Promise((resolve, reject) => {
      const id = ++this.nextId;
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`${method} timed out; delivery is unverified`));
      }, this.timeoutMs);
      this.pending.set(id, { resolve, reject, timer });
      this.surface.parent.postMessage({ jsonrpc: '2.0', id, method, params }, '*');
    });
  }

  async initialize(appInfo = { name: 'mamba-host-probe', version: '0.1.2' }) {
    if (this.surface.parent === this.surface) throw new Error('请从 MCP 工具打开面板；普通浏览器页面没有宿主桥。');
    const result = await this.request('ui/initialize', {
      appInfo,
      appCapabilities: { availableDisplayModes: ['inline', 'fullscreen'] },
      protocolVersion: '2026-01-26',
    });
    if (result?.protocolVersion !== '2026-01-26') throw new Error('Unsupported MCP Apps protocol');
    this.surface.parent.postMessage({ jsonrpc: '2.0', method: 'ui/notifications/initialized', params: {} }, '*');
    return result;
  }

  async callTool(name, args) {
    const result = await this.request('tools/call', { name, arguments: args });
    if (result?.isError) throw new Error(result.content?.filter((c) => c.type === 'text').map((c) => c.text).join('\n') || 'Tool failed');
    return result;
  }

  async sendMessage(text) {
    const result = await this.request('ui/message', { role: 'user', content: [{ type: 'text', text }] });
    if (result?.isError) throw new Error('Host rejected the message');
    return result;
  }

  close() {
    this.closed = true;
    this.surface.removeEventListener('message', this.receive);
    for (const item of this.pending.values()) {
      clearTimeout(item.timer);
      item.reject(new Error('Host bridge closed before response'));
    }
    this.pending.clear();
  }
}
