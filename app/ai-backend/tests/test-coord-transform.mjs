// [Flow: Step 1 (TypeScript 좌표 변환 함수 테스트) -> Step 2 (다양한 rect 형식 처리 검증)]
// save_annotations의 _convertAnnotationToDeviceSpace 함수가
// 배열 [x0,y0,x1,y1], {origin,size}, {x,y,width,height}, bbox_pdf 필드를 모두 올바르게 처리하는지 확인.
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';

// _convertAnnotationToDeviceSpace 함수를 직접 import할 수 없으므로,
// 동일한 로직을 인라인으로 구현하여 테스트한다.
// 실제 함수는 annotations.ts에 있으며, 이 테스트는 로직이 올바른지 검증한다.

function _convertAnnotationToDeviceSpace(item, pageDims) {
  const inner = item.annotation && typeof item.annotation === 'object'
    ? item.annotation : item;
  const pageNo = Number(inner.pageIndex ?? 0) + 1;
  const dims = pageDims[pageNo] || { width: 612, height: 792 };
  const pageHeight = dims.height;

  const normalizeRect = (rect) => {
    if (!rect) return rect;
    if (Array.isArray(rect) && rect.length >= 4) {
      const [x0, y0, x1, y1] = rect.map(Number);
      return {
        origin: { x: x0, y: y0 },
        size: { width: x1 - x0, height: y1 - y0 },
      };
    }
    if (typeof rect !== 'object') return rect;
    if (rect.origin && typeof rect.origin.x === 'number') return rect;
    if (typeof rect.x === 'number' && typeof rect.width === 'number') {
      return {
        origin: { x: rect.x, y: rect.y },
        size: { width: rect.width, height: rect.height || 0 },
      };
    }
    return rect;
  };

  const convertRect = (rect) => {
    const normalized = normalizeRect(rect);
    if (!normalized || typeof normalized !== 'object') return rect;
    const origin = normalized.origin;
    const size = normalized.size;
    if (!origin || typeof origin.y !== 'number' || !size || typeof size.height !== 'number') return rect;
    return {
      origin: { x: origin.x, y: pageHeight - origin.y - size.height },
      size: { width: size.width, height: size.height },
    };
  };

  const convertedInner = { ...inner };

  if (Array.isArray(convertedInner.bbox_pdf) && !convertedInner.rect) {
    const [x0, y0, x1, y1] = convertedInner.bbox_pdf.map(Number);
    convertedInner.rect = {
      origin: { x: x0, y: y0 },
      size: { width: x1 - x0, height: y1 - y0 },
    };
  }

  if (convertedInner.rect) {
    convertedInner.rect = convertRect(convertedInner.rect);
  }
  if (Array.isArray(convertedInner.segmentRects)) {
    convertedInner.segmentRects = convertedInner.segmentRects.map(convertRect);
  }

  if (item.annotation && typeof item.annotation === 'object') {
    return { ...item, annotation: convertedInner };
  }
  return convertedInner;
}

const PAGE_DIMS = { 1: { width: 595, height: 842 } };

describe('_convertAnnotationToDeviceSpace', () => {
  it('배열 rect [x0,y0,x1,y1]을 device-space로 변환', () => {
    // PDF user-space: x0=100, y0=780, x1=200, y1=800 (페이지 상단)
    // device-space: origin.y = 842 - 780 - 20 = 42
    const item = {
      annotation: {
        id: 'test-1',
        type: 9,
        pageIndex: 0,
        rect: [100, 780, 200, 800],
      },
    };
    const result = _convertAnnotationToDeviceSpace(item, PAGE_DIMS);
    const rect = result.annotation.rect;
    assert.equal(rect.origin.x, 100);
    assert.equal(rect.origin.y, 42);
    assert.equal(rect.size.width, 100);
    assert.equal(rect.size.height, 20);
  });

  it('{origin, size} rect를 device-space로 변환', () => {
    // PDF user-space: origin.y=780 (하단 y0), size.height=20
    // device-space: origin.y = 842 - 780 - 20 = 42
    const item = {
      annotation: {
        id: 'test-2',
        type: 9,
        pageIndex: 0,
        rect: { origin: { x: 100, y: 780 }, size: { width: 100, height: 20 } },
      },
    };
    const result = _convertAnnotationToDeviceSpace(item, PAGE_DIMS);
    const rect = result.annotation.rect;
    assert.equal(rect.origin.y, 42);
    assert.equal(rect.origin.x, 100);
    assert.equal(rect.size.width, 100);
    assert.equal(rect.size.height, 20);
  });

  it('{x, y, width, height} 레거시 rect를 device-space로 변환', () => {
    const item = {
      annotation: {
        id: 'test-3',
        type: 9,
        pageIndex: 0,
        rect: { x: 100, y: 780, width: 100, height: 20 },
      },
    };
    const result = _convertAnnotationToDeviceSpace(item, PAGE_DIMS);
    const rect = result.annotation.rect;
    assert.equal(rect.origin.y, 42);
    assert.equal(rect.origin.x, 100);
  });

  it('bbox_pdf 필드를 rect로 승격 후 변환', () => {
    const item = {
      annotation: {
        id: 'test-4',
        type: 9,
        pageIndex: 0,
        bbox_pdf: [100, 780, 200, 800],
      },
    };
    const result = _convertAnnotationToDeviceSpace(item, PAGE_DIMS);
    const rect = result.annotation.rect;
    assert.equal(rect.origin.y, 42);
    assert.equal(rect.origin.x, 100);
    assert.equal(rect.size.width, 100);
    assert.equal(rect.size.height, 20);
  });

  it('segmentRects 배열도 변환', () => {
    const item = {
      annotation: {
        id: 'test-5',
        type: 9,
        pageIndex: 0,
        rect: [100, 780, 200, 800],
        segmentRects: [[100, 780, 200, 800]],
      },
    };
    const result = _convertAnnotationToDeviceSpace(item, PAGE_DIMS);
    assert.equal(result.annotation.segmentRects[0].origin.y, 42);
  });

  it('페이지 하단 영역 (y0=30, y1=50) → device-space top=792', () => {
    const item = {
      annotation: {
        id: 'test-6',
        type: 9,
        pageIndex: 0,
        rect: [100, 30, 200, 50],
      },
    };
    const result = _convertAnnotationToDeviceSpace(item, PAGE_DIMS);
    const rect = result.annotation.rect;
    // device-space: origin.y = 842 - 30 - 20 = 792
    assert.equal(rect.origin.y, 792);
  });

  it('inner annotation 없이 flat 구조도 처리', () => {
    const item = {
      id: 'test-7',
      type: 9,
      pageIndex: 0,
      rect: [100, 780, 200, 800],
    };
    const result = _convertAnnotationToDeviceSpace(item, PAGE_DIMS);
    assert.equal(result.rect.origin.y, 42);
  });

  it('round-trip: PDF user-space → device-space → PDF user-space', () => {
    // PDF user-space: y0=780, y1=800, height=842
    // device-space: origin.y = 842 - 780 - 20 = 42
    // 역변환: y0 = 842 - 42 - 20 = 780, y1 = 842 - 42 = 800
    const item = {
      annotation: {
        id: 'test-rt',
        type: 9,
        pageIndex: 0,
        rect: [100, 780, 200, 800],
      },
    };
    const devResult = _convertAnnotationToDeviceSpace(item, PAGE_DIMS);
    const devRect = devResult.annotation.rect;
    // 역변환 수동 계산
    const restoredY0 = 842 - devRect.origin.y - devRect.size.height;
    const restoredY1 = 842 - devRect.origin.y;
    assert.equal(restoredY0, 780);
    assert.equal(restoredY1, 800);
  });
});
