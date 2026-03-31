import { getBackendUrl } from '$lib/config';

type RosbridgeStatus = 'idle' | 'connecting' | 'connected' | 'disconnected' | 'error';
export type RosTopicInfo = {
  name: string;
  type: string;
};

type SubscriptionOptions = {
  type?: string;
  throttle_rate?: number;
  queue_length?: number;
};

type SubscriptionHandler = (message: Record<string, unknown>) => void;

type Subscription = {
  topic: string;
  handlers: Set<SubscriptionHandler>;
  options: SubscriptionOptions;
};

type PendingServiceCall = {
  resolve: (payload: Record<string, unknown>) => void;
  reject: (error: Error) => void;
  timer: ReturnType<typeof setTimeout>;
};

class RosbridgeClient {
  private ws: WebSocket | null = null;
  private status: RosbridgeStatus = 'idle';
  private subscriptions = new Map<string, Subscription>();
  private pendingServiceCalls = new Map<string, PendingServiceCall>();
  private serviceRequestSeq = 0;
  private connectPromise: Promise<void> | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectAttempt = 0;
  private statusListeners = new Set<(status: RosbridgeStatus) => void>();

  getStatus() {
    return this.status;
  }

  onStatusChange(handler: (status: RosbridgeStatus) => void) {
    this.statusListeners.add(handler);
    return () => {
      this.statusListeners.delete(handler);
    };
  }

  connect() {
    if (this.status === 'connected' && this.ws) return Promise.resolve();
    if (this.connectPromise) return this.connectPromise;

    this.updateStatus('connecting');
    const url = this.buildUrl();
    if (!url) {
      this.updateStatus('error');
      return Promise.reject(new Error('rosbridge url not available'));
    }

    this.connectPromise = new Promise((resolve, reject) => {
      const ws = new WebSocket(url);
      this.ws = ws;

      ws.onopen = () => {
        this.updateStatus('connected');
        this.connectPromise = null;
        this.reconnectAttempt = 0;
        for (const sub of this.subscriptions.values()) {
          this.sendSubscribe(sub.topic, sub.options);
        }
        resolve();
      };

      ws.onmessage = (event) => {
        if (!event?.data) return;
        let payload: Record<string, unknown> | null = null;
        try {
          payload = JSON.parse(event.data);
        } catch {
          return;
        }
        if (!payload) return;
        if (payload.op === 'publish') {
          const topic = payload.topic as string | undefined;
          if (!topic) return;
          const sub = this.subscriptions.get(topic);
          if (!sub) return;
          for (const handler of sub.handlers) {
            handler(payload.msg as Record<string, unknown>);
          }
          return;
        }
        if (payload.op === 'service_response') {
          this.handleServiceResponse(payload);
        }
      };

      ws.onerror = () => {
        this.rejectPendingServiceCalls(new Error('rosbridge connection error'));
        this.updateStatus('error');
        this.connectPromise = null;
        this.scheduleReconnect();
        reject(new Error('rosbridge connection error'));
      };

      ws.onclose = () => {
        this.rejectPendingServiceCalls(new Error('rosbridge connection closed'));
        this.updateStatus('disconnected');
        this.connectPromise = null;
        this.ws = null;
        this.scheduleReconnect();
      };
    });

    return this.connectPromise;
  }

  subscribe(topic: string, handler: SubscriptionHandler, options: SubscriptionOptions = {}) {
    if (!topic) return () => {};

    let entry = this.subscriptions.get(topic);
    if (!entry) {
      entry = {
        topic,
        handlers: new Set<SubscriptionHandler>(),
        options
      };
      this.subscriptions.set(topic, entry);
    }

    entry.handlers.add(handler);

    if (this.status === 'connected' && this.ws) {
      this.sendSubscribe(topic, entry.options);
    } else if (typeof window !== 'undefined') {
      this.connect().catch(() => {
        // ignore connect errors; component can show fallback
      });
    }

    return () => {
      const current = this.subscriptions.get(topic);
      if (!current) return;
      current.handlers.delete(handler);
      if (current.handlers.size === 0) {
        this.subscriptions.delete(topic);
        if (this.ws && this.status === 'connected') {
          this.sendUnsubscribe(topic);
        }
      }
    };
  }

  private sendSubscribe(topic: string, options: SubscriptionOptions) {
    if (!this.ws || this.status !== 'connected') return;
    const payload = {
      op: 'subscribe',
      topic,
      type: options.type,
      queue_length: options.queue_length ?? 1,
      throttle_rate: options.throttle_rate ?? 100
    };
    this.ws.send(JSON.stringify(payload));
  }

  private sendUnsubscribe(topic: string) {
    if (!this.ws || this.status !== 'connected') return;
    this.ws.send(JSON.stringify({ op: 'unsubscribe', topic }));
  }

  async callService(
    service: string,
    args: Record<string, unknown> = {},
    timeoutMs = 3000
  ): Promise<Record<string, unknown>> {
    if (!service) {
      throw new Error('service is required');
    }
    await this.connect();
    if (!this.ws || this.status !== 'connected') {
      throw new Error('rosbridge is not connected');
    }

    const id = `svc-${Date.now()}-${++this.serviceRequestSeq}`;
    const payload = {
      op: 'call_service',
      service,
      args,
      id
    };

    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pendingServiceCalls.delete(id);
        reject(new Error(`service call timed out: ${service}`));
      }, timeoutMs);
      this.pendingServiceCalls.set(id, { resolve, reject, timer });
      try {
        this.ws?.send(JSON.stringify(payload));
      } catch {
        clearTimeout(timer);
        this.pendingServiceCalls.delete(id);
        reject(new Error(`failed to call service: ${service}`));
      }
    });
  }

  async listTopics(timeoutMs = 3000): Promise<RosTopicInfo[]> {
    const response = await this.callService('/rosapi/topics', {}, timeoutMs);
    const values = response.values as Record<string, unknown> | undefined;
    const topicNamesRaw = values?.topics;
    const topicTypesRaw = values?.types;
    const topicNames = Array.isArray(topicNamesRaw)
      ? topicNamesRaw.filter((value): value is string => typeof value === 'string')
      : [];
    const topicTypes = Array.isArray(topicTypesRaw) ? topicTypesRaw : [];

    return topicNames.map((name, index) => ({
      name,
      type: typeof topicTypes[index] === 'string' ? topicTypes[index] : ''
    }));
  }

  private handleServiceResponse(payload: Record<string, unknown>) {
    const id = payload.id != null ? String(payload.id) : '';
    if (!id) return;
    const pending = this.pendingServiceCalls.get(id);
    if (!pending) return;

    clearTimeout(pending.timer);
    this.pendingServiceCalls.delete(id);
    const result = payload.result;
    if (result === false) {
      pending.reject(new Error('rosbridge service call failed'));
      return;
    }
    pending.resolve(payload);
  }

  private rejectPendingServiceCalls(error: Error) {
    for (const [id, pending] of this.pendingServiceCalls.entries()) {
      clearTimeout(pending.timer);
      pending.reject(error);
      this.pendingServiceCalls.delete(id);
    }
  }

  private scheduleReconnect() {
    if (this.reconnectTimer || this.subscriptions.size === 0) return;
    const delay = Math.min(1000 * 2 ** this.reconnectAttempt, 15000);
    this.reconnectAttempt += 1;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null;
      this.connect().catch(() => {
        // retry continues on next schedule
      });
    }, delay);
  }

  private updateStatus(next: RosbridgeStatus) {
    if (this.status === next) return;
    this.status = next;
    for (const listener of this.statusListeners) {
      listener(next);
    }
  }

  private buildUrl() {
    if (typeof window === 'undefined') return '';
    const backendUrl = getBackendUrl();
    try {
      const parsed = new URL(backendUrl);
      const protocol = parsed.protocol === 'https:' ? 'wss' : 'ws';
      const host = parsed.hostname || window.location.hostname || 'localhost';
      return `${protocol}://${host}:9090`;
    } catch {
      const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
      const host = window.location.hostname || 'localhost';
      return `${protocol}://${host}:9090`;
    }
  }
}

let singleton: RosbridgeClient | null = null;

export const getRosbridgeClient = () => {
  if (!singleton) {
    singleton = new RosbridgeClient();
  }
  return singleton;
};
