/**
 * HTTP helpers y cliente WebSocket para la API Zebra.
 */

const BASE = '/api'

export async function fetchProviders() {
  const res = await fetch(`${BASE}/providers`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function fetchModels(provider: string) {
  const res = await fetch(`${BASE}/models/${provider}`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function fetchExecutions(limit = 20) {
  const res = await fetch(`${BASE}/executions?limit=${limit}`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function fetchExecutionDetail(id: string) {
  const res = await fetch(`${BASE}/executions/${id}`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

/**
 * Abre una conexion WebSocket y ejecuta el pipeline.
 * Llama a onProgress con cada mensaje de progreso.
 * Resuelve con el FinalOutput al completar.
 * Rechaza con Error si hay error.
 */
export function executeViaWebSocket(
  request: string,
  provider: string,
  model: string,
  onProgress: (msg: ProgressMessage) => void,
): Promise<any> {
  return new Promise((resolve, reject) => {
    const protocol = location.protocol === 'https:' ? 'wss' : 'ws'
    const ws = new WebSocket(`${protocol}://${location.host}/api/ws/execute`)

    ws.onopen = () => {
      ws.send(JSON.stringify({ request, provider, model }))
    }

    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data)
      if (msg.type === 'progress') {
        onProgress(msg as ProgressMessage)
      } else if (msg.type === 'complete') {
        ws.close()
        resolve(msg.result)
      } else if (msg.type === 'error') {
        ws.close()
        reject(new Error(msg.message))
      }
    }

    ws.onerror = () => reject(new Error('WebSocket connection error'))
    ws.onclose = (e) => {
      if (!e.wasClean) reject(new Error('WebSocket closed unexpectedly'))
    }
  })
}

export interface ProgressMessage {
  type: 'progress'
  state: string
  agent_name: string | null
  duration_ms?: number
  tokens?: number
  from_cache?: boolean
  model_used?: string
  revision_count: number
  traces_so_far: number
}
