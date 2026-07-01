import React from "react";

const base = "bg-surface-container-high animate-pulse";

export function Skeleton({ className = "" }) {
  return <div className={`${base} ${className}`} />;
}

export function SkeletonText({ lines = 1, className = "" }) {
  return (
    <div className={`space-y-2 ${className}`}>
      {Array.from({ length: lines }).map((_, i) => (
        <div key={i} className={`${base} h-4 w-full`} />
      ))}
    </div>
  );
}

export function SkeletonCard({ rows = 1 }) {
  return (
    <div className="border border-outline-variant/30 p-4 bg-surface-container-lowest">
      <div className="flex justify-between items-start mb-3">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="h-8 w-8" />
      </div>
      <Skeleton className="h-8 w-20 mb-2" />
      {rows > 1 && <SkeletonText lines={rows - 1} />}
    </div>
  );
}

export function SkeletonTable({ columns = 4, rows = 5 }) {
  return (
    <div className="w-full">
      <div className="flex border-b border-outline-variant/30">
        {Array.from({ length: columns }).map((_, i) => (
          <div key={i} className="flex-1 px-4 py-3">
            <Skeleton className="h-3 w-16" />
          </div>
        ))}
      </div>
      {Array.from({ length: rows }).map((_, r) => (
        <div key={r} className="flex border-b border-outline-variant/20">
          {Array.from({ length: columns }).map((_, c) => (
            <div key={c} className="flex-1 px-4 py-3">
              <Skeleton className="h-4 w-full" />
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

export function SkeletonPageResult() {
  return (
    <div className="flex-1 flex overflow-hidden">
      <div className="w-1/3 border-r border-outline-variant p-4 space-y-4">
        <Skeleton className="h-4 w-20" />
        <Skeleton className="h-4 w-16" />
        <div className="space-y-2">
          {Array.from({ length: 8 }).map((_, i) => (
            <Skeleton key={i} className="h-10 w-full" />
          ))}
        </div>
      </div>
      <div className="flex-1 p-4 space-y-4">
        <Skeleton className="h-6 w-1/2" />
        <SkeletonText lines={12} />
      </div>
    </div>
  );
}

export default Skeleton;
