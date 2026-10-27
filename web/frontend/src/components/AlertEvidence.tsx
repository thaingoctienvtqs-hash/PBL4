import { useCallback, useEffect, useState } from 'react'
import { api, errorMessage } from '../api/client'
import { usePolling } from '../hooks/usePolling'
import type { Evidence, EvidenceDetail, EvidenceMedia } from '../types'
import { formatEventTime } from '../utils/datetime'

function EvidenceImage({ media }: { media: EvidenceMedia }) {
  const [url, setUrl] = useState('')
  const [error, setError] = useState('')
  useEffect(() => {
    const controller = new AbortController()
    let active = true
    let objectUrl = ''
    setUrl('')
    setError('')
    api.get<Blob>('/evidence-media/' + media.id + '/file', {
      responseType: 'blob', signal: controller.signal,
    }).then(({ data }) => {
      if (!active) return
      if (!data.type.startsWith('image/')) {
        setError('File không phải ảnh có thể xem.')
        return
      }
      objectUrl = URL.createObjectURL(data)
      setUrl(objectUrl)
    }).catch((reason) => {
      if (active && !controller.signal.aborted) setError(errorMessage(reason))
    })
    return () => {
      active = false
      controller.abort()
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [media.id])

  if (error) return <p role="status">{error}</p>
  if (!url) return <p role="status">Đang tải ảnh bằng chứng…</p>
  return <a className="evidence-thumb" href={url} target="_blank" rel="noreferrer" aria-label={'Mở ảnh bằng chứng ' + media.id}><img src={url} alt={'Ảnh bằng chứng ' + media.id} /></a>
}

export function AlertEvidence({ alertId }: { alertId: number }) {
  const fetchEvidence = useCallback(async (signal: AbortSignal) => {
    const { data } = await api.get<Evidence[]>('/alerts/' + alertId + '/evidences', { signal })
    const details = await Promise.all(data.map(async (item) => {
      const response = await api.get<EvidenceDetail>('/evidences/' + item.id, { signal })
      return response.data
    }))
    return details
  }, [alertId])
  const { data, error, loading, refresh } = usePolling(fetchEvidence, 2000)

  return <section className="evidence-media-section" aria-label="Bằng chứng cảnh báo">
    <h4>Bằng chứng <button className="button button-small button-secondary" type="button" onClick={refresh}>Làm mới</button></h4>
    {loading && <p role="status">Đang tải thông tin bằng chứng…</p>}
    {error && <p role="status">{error}</p>}
    {!loading && !error && (!data || data.length === 0) && <p role="status">Evidence pending — chưa có bằng chứng được backend liên kết.</p>}
    {data?.map((item) => <div key={item.id}>
      <b>{item.evidence_code}</b>
      <p>{item.event_type} · {formatEventTime(item.detected_at)} · {item.processing_status}</p>
      {item.description && <p>{item.description}</p>}
      {item.media.filter((media) => media.media_type === 'image').length === 0
        ? <p role="status">Evidence pending — chưa có ảnh được backend phục vụ an toàn.</p>
        : <div className="evidence-image-grid">{item.media.filter((media) => media.media_type === 'image').map((media) => <EvidenceImage key={media.id} media={media} />)}</div>}
      {item.media.some((media) => media.media_type === 'video') && <p>Video đã được ghi nhận; bản xem trước này chỉ tải ảnh.</p>}
    </div>)}
  </section>
}
