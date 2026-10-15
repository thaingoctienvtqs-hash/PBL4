import { useEffect, useState } from 'react'
import { Image as ImageIcon, Upload, X } from 'lucide-react'

const MAX_IMAGE_BYTES = 5 * 1024 * 1024
const ACCEPTED_TYPES = new Set(['image/jpeg', 'image/png', 'image/webp'])
const MANAGED_IMAGE_PATH = /^\/uploads\/artworks\/[a-f0-9]{32}\.(?:jpg|png|webp)$/

interface ArtworkImageProps {
  src?: string | null
  alt: string
  className?: string
}

export function ArtworkImage({ src, alt, className = '' }: ArtworkImageProps) {
  const [failedSrc, setFailedSrc] = useState<string | null>(null)
  useEffect(() => setFailedSrc(null), [src])

  if (!src || (!src.startsWith('blob:') && !MANAGED_IMAGE_PATH.test(src)) || failedSrc === src) {
    return <div className={`${className} artwork-image-placeholder`} aria-label={alt} role="img"><ImageIcon size={24} strokeWidth={1.4} /></div>
  }
  return <img className={className} src={src} alt={alt} loading="lazy" onError={() => setFailedSrc(src)} />
}

interface ArtworkImagePickerProps {
  imageUrl?: string | null
  inventoryCode: string
  selectedFile: File | null
  onFileChange: (file: File | null) => void
  onUpload?: () => void
  uploading?: boolean
  uploadProgress?: number
  error?: string
  disabled?: boolean
}

export function ArtworkImagePicker({ imageUrl, inventoryCode, selectedFile, onFileChange, onUpload, uploading = false, uploadProgress = 0, error, disabled = false }: ArtworkImagePickerProps) {
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [validationError, setValidationError] = useState('')

  useEffect(() => {
    if (!selectedFile) {
      setPreviewUrl(null)
      return
    }
    const url = URL.createObjectURL(selectedFile)
    setPreviewUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [selectedFile])

  function chooseFile(file: File | undefined) {
    if (disabled || uploading) return
    setValidationError('')
    if (!file) return
    if (file.size > MAX_IMAGE_BYTES) {
      setValidationError('Ảnh phải có dung lượng tối đa 5 MB.')
      onFileChange(null)
      return
    }
    if (file.type && !ACCEPTED_TYPES.has(file.type)) {
      setValidationError('Chỉ chọn ảnh JPEG, PNG hoặc WebP.')
      onFileChange(null)
      return
    }
    onFileChange(file)
  }

  const shownImage = previewUrl ?? imageUrl
  const hasCurrentImage = !!imageUrl && MANAGED_IMAGE_PATH.test(imageUrl)
  return <div className="artwork-image-picker">
    <div className="artwork-image-picker-preview">
      <ArtworkImage src={shownImage} alt={`Ảnh tác phẩm ${inventoryCode}`} className="artwork-picker-image" />
      <div className="artwork-picker-meta"><b>{selectedFile ? selectedFile.name : hasCurrentImage ? 'Ảnh hiện tại' : imageUrl ? 'Ảnh cũ không khả dụng' : 'Chưa có ảnh'}</b><span>JPEG, PNG hoặc WebP · tối đa 5 MB</span></div>
    </div>
    <div className="artwork-picker-actions">
      <label className={`button button-secondary artwork-file-button ${disabled || uploading ? 'button-disabled' : ''}`}><Upload size={14} /> Chọn ảnh
        <input type="file" accept="image/jpeg,image/png,image/webp" disabled={disabled || uploading} onChange={(event) => { chooseFile(event.target.files?.[0]); event.currentTarget.value = '' }} />
      </label>
      {selectedFile && <button className="button button-secondary" type="button" disabled={disabled || uploading} onClick={() => { setValidationError(''); onFileChange(null) }}><X size={14} /> Hủy chọn</button>}
      {onUpload && <button className="button button-primary" type="button" disabled={!selectedFile || uploading || disabled} onClick={onUpload}><Upload size={14} />{uploading ? `Đang tải ${uploadProgress}%…` : hasCurrentImage ? 'Thay ảnh' : 'Tải ảnh lên'}</button>}
      {!onUpload && selectedFile && <span className="artwork-picker-hint">Ảnh sẽ được tải lên khi lưu tác phẩm.</span>}
    </div>
    {uploading && <div className="artwork-upload-progress" role="progressbar" aria-label="Tiến độ tải ảnh" aria-valuenow={uploadProgress} aria-valuemin={0} aria-valuemax={100}><span style={{ width: `${uploadProgress}%` }} /></div>}
    {(validationError || error) && <p className="artwork-upload-error" role="alert">{validationError || error}</p>}
  </div>
}
