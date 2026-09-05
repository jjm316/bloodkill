// 通用确认/取消弹窗：每次使用只改标题、正文、两个按钮的文案与点击行为
// （issue 23 抽象复用要求，第一个使用方是干涉投票"是否为 X 挡刀？"）。

export interface ConfirmDialogProps {
  title: string;
  body?: React.ReactNode;
  confirmText: string;
  cancelText: string;
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmDialog({ title, body, confirmText, cancelText, onConfirm, onCancel }: ConfirmDialogProps) {
  return (
    <div className="modal-overlay" role="presentation">
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="modal-title">
        <h3 id="modal-title">{title}</h3>
        {body !== undefined && <div className="modal-body">{body}</div>}
        <div className="modal-actions">
          <button className="modal-confirm" onClick={onConfirm}>{confirmText}</button>
          <button className="modal-cancel" onClick={onCancel}>{cancelText}</button>
        </div>
      </div>
    </div>
  );
}
