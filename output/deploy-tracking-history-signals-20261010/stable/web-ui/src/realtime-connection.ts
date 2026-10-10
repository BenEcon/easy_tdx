/** Old socket events cannot change a newly selected symbol or replacement connection. */
export function bindRealtimeSocket(
  socket: Pick<WebSocket, 'onopen' | 'onmessage' | 'onerror' | 'onclose'>,
  isCurrent: () => boolean,
  handlers: {
    connected: () => void
    tick: (value: Record<string, unknown>) => void
    error: (message: string) => void
    closed: (event: CloseEvent) => void
  },
) {
  socket.onopen = () => { if (isCurrent()) handlers.connected() }
  socket.onmessage = event => {
    if (!isCurrent()) return
    try {
      const payload = JSON.parse(String(event.data))
      if (!payload || Array.isArray(payload) || typeof payload !== 'object') throw new Error('invalid')
      if (payload.type === 'error') handlers.error(String(payload.msg || '实时订阅失败'))
      else if (payload.type === 'tick' || payload.type === 'signal') handlers.tick(payload)
    } catch { handlers.error('实时消息格式无效，未更新行情') }
  }
  socket.onerror = () => { if (isCurrent()) handlers.error('实时连接失败，请检查网络或登录状态') }
  socket.onclose = event => { if (isCurrent()) handlers.closed(event) }
}
