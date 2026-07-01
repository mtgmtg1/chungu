import React from "react";

export function AnimatedList({
  children,
  baseDelay = 0,
  stagger = 30,
  className = ""
}) {
  return (
    <div className={className}>
      {React.Children.map(children, (child, index) => {
        if (!child) return child;
        return (
          <div
            className="animate-stagger-enter"
            style={{ animationDelay: `${baseDelay + index * stagger}ms` }}
          >
            {child}
          </div>
        );
      })}
    </div>
  );
}

export function AnimatedRow({ index = 0, stagger = 30, children }) {
  return (
    <div
      className="animate-stagger-enter"
      style={{ animationDelay: `${index * stagger}ms` }}
    >
      {children}
    </div>
  );
}

export default AnimatedList;
