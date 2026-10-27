import { createServer, preview } from 'vite'
import { fileURLToPath } from 'node:url'

export default async function () {
  if (process.env.DROPDOWN_EXTERNAL_SERVER || process.env.DROPDOWN_BASE_URL) return
  const root = fileURLToPath(new URL('../', import.meta.url))
  const address = { host: '127.0.0.1', port: 5187, strictPort: true }
  if (process.env.DROPDOWN_PRODUCTION) {
    const server = await preview({ root, preview: address })
    return async () => { server.httpServer.closeAllConnections(); await new Promise(resolve => server.httpServer.close(resolve)) }
  }
  const server = await createServer({ root, server: address })
  await server.listen()
  return () => server.close()
}
