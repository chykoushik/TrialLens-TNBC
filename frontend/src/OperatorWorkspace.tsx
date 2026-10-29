import { useState } from 'react'
import { api } from './api'
import { Button } from './ui'
import NemotronReview from './NemotronReview'
import type { Trial } from './types'

export default function OperatorWorkspace({ trials }: { trials: Trial[] }) {
  const [token, setToken] = useState('')
  const [authenticated, setAuthenticated] = useState(false)
  const [selected, setSelected] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const trial = trials.find(item => item.nct_id === selected)
  async function unlock() {
    setBusy(true); setError('')
    try { await api('/operator/session', undefined, undefined, { Authorization: `Bearer ${token}` }); setAuthenticated(true) }
    catch { setError('Operator access was not accepted. Check the server configuration and access code.') }
    finally { setBusy(false) }
  }
  return <section><h2>Operator workspace</h2><p>Source-scoped paid requests and mapping review require operator authentication. Credentials remain on the server. No request runs on sign-in.</p>{!authenticated ? <form onSubmit={e => { e.preventDefault(); void unlock() }}><label>Operator access code<input type="password" autoComplete="off" value={token} onChange={e => setToken(e.target.value)} /></label><Button type="submit" disabled={!token || busy}>Unlock operator tools</Button></form> : <><Button onClick={() => { setAuthenticated(false); setToken(''); setSelected('') }}>Lock and clear access</Button><label>Saved trial<select value={selected} onChange={e => setSelected(e.target.value)}><option value="">Choose a trial</option>{trials.map(item => <option value={item.nct_id ?? ''} key={item.nct_id}>{item.nct_id} · {item.title}</option>)}</select></label>{trial && <NemotronReview key={trial.nct_id} trial={trial} operatorToken={token} />}</>}{error && <p role="alert">{error}</p>}</section>
}
