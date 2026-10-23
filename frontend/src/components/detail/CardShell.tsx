import React from "react";
import { GripVertical, Maximize2 } from "lucide-react";

interface Props {
  onExpand: () => void;
  onDragStart: (e: React.DragEvent) => void;
  onDragOver: (e: React.DragEvent) => void;
  onDrop: (e: React.DragEvent) => void;
  onDragEnd: (e: React.DragEvent) => void;
  isDragging: boolean;
  isDragOver: boolean;
  children: React.ReactNode;
}

/**
 * Wraps a detail card with a hover-revealed control strip: a drag grip (reorder)
 * and a maximize button (expand-to-focus). Controls are desktop-only (`hidden
 * lg:*`) since native HTML5 drag has no touch support — on mobile the card renders
 * exactly as before, so the bottom sheet stays fully functional.
 */
export const CardShell: React.FC<Props> = ({
  onExpand,
  onDragStart,
  onDragOver,
  onDrop,
  onDragEnd,
  isDragging,
  isDragOver,
  children,
}) => (
  <div
    onDragOver={onDragOver}
    onDrop={onDrop}
    className={`group relative rounded-lg transition ${isDragging ? "opacity-40" : ""} ${
      isDragOver ? "ring-2 ring-sky-500/60" : ""
    }`}
  >
    <div className="hidden lg:flex items-center justify-between px-1 mb-1 h-4 opacity-0 group-hover:opacity-100 transition-opacity">
      <span
        draggable
        onDragStart={onDragStart}
        onDragEnd={onDragEnd}
        title="Drag to reorder card"
        className="inline-flex items-center gap-1 text-[10px] text-gray-600 hover:text-gray-300 cursor-grab active:cursor-grabbing select-none"
      >
        <GripVertical size={12} /> drag
      </span>
      <button
        onClick={onExpand}
        title="Expand card"
        className="inline-flex items-center text-gray-500 hover:text-gray-200"
      >
        <Maximize2 size={13} />
      </button>
    </div>
    {children}
  </div>
);
