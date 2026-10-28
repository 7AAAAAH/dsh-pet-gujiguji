/**
 * Client half of dsh-pet-gujiguji.
 *
 * Renders the GujiGuji sprite sheet in the window overlay and swaps the
 * animation row from the Host's agent-status stream. The pet is a normal slot
 * entry, so it is disposed with the plugin instead of leaving a detached DOM
 * tree behind on document.body.
 *
 * Sprite geometry: 1536x1872, 192x208 cells, 8 columns x 9 rows.
 * Rows: idle, running-right, running-left, waving, jumping, failed, waiting,
 * running, review.
 */

window.__ModuleLoader__.load({
  id: 'dsh-pet-gujiguji',
  factory(require) {
    const React = require('react')
    const h = React.createElement
    const { useCallback, useEffect, useRef, useState } = React

    const SPRITE_ROUTE = '/dsh-pet-gujiguji/spritesheet.webp'
    const STATE_ROUTE = '/dsh-pet-gujiguji/state'
    const SETTINGS_ROUTE = '/dsh-pet-gujiguji/settings'
    const POSITION_KEY = 'dsh-pet-gujiguji:position'
    // Ignore the old `visible=false` value that could hide the pet forever.
    const VISIBLE_KEY = 'dsh-pet-gujiguji:visible:v2'

    const CELL_W = 192
    const CELL_H = 208
    const SCALE = 0.62
    const DISP_W = Math.round(CELL_W * SCALE)
    const DISP_H = Math.round(CELL_H * SCALE)

    const ROWS = [
      { state: 'idle', frames: 6 },
      { state: 'running-right', frames: 8 },
      { state: 'running-left', frames: 8 },
      { state: 'waving', frames: 4 },
      { state: 'jumping', frames: 5 },
      { state: 'failed', frames: 8 },
      { state: 'waiting', frames: 6 },
      { state: 'running', frames: 6 },
      { state: 'review', frames: 6 },
    ]
    const ROW_INDEX = Object.fromEntries(ROWS.map((row, index) => [row.state, index]))

    const FRAME_MS = {
      idle: 220,
      waving: 200,
      jumping: 130,
      running: 90,
      'running-right': 90,
      'running-left': 90,
      waiting: 240,
      failed: 150,
      review: 200,
    }

    function rowForStatus(status) {
      switch (status) {
        case 'running': return 'running'
        case 'waiting': return 'waiting'
        case 'failed': return 'failed'
        case 'review': return 'review'
        case 'idle':
        default: return 'idle'
      }
    }

    function endpoint(path) {
      return new URL(path, document.baseURI).href
    }

    function readStoredPosition() {
      try {
        const value = JSON.parse(localStorage.getItem(POSITION_KEY) || 'null')
        if (value && Number.isFinite(value.left) && Number.isFinite(value.top)) return value
      } catch { /* ignore malformed storage */ }
      return null
    }

    function readStoredVisibility() {
      try {
        const value = localStorage.getItem(VISIBLE_KEY)
        return value === null ? true : value !== 'false'
      } catch {
        return true
      }
    }

    function store(key, value) {
      try { localStorage.setItem(key, value) } catch { /* best effort */ }
    }

    /**
     * Subscribe to the Host's SSE status stream. The browser reconnects by
     * itself, and the returned disposer stops reconnecting after unmount.
     */
    function watchAgentState(onState) {
      let alive = true
      try {
        const source = new EventSource(endpoint(STATE_ROUTE))
        source.onmessage = (event) => {
          if (!alive) return
          try {
            const data = JSON.parse(event.data)
            if (data && typeof data === 'object') onState(data)
          } catch { /* ignore malformed frame */ }
        }
        return () => {
          alive = false
          source.close()
        }
      } catch {
        return () => {}
      }
    }

    function syncDesktopVisibility(visible) {
      try {
        fetch(endpoint(SETTINGS_ROUTE), {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ visible }),
          keepalive: true,
        }).catch(() => {})
      } catch { /* the in-app pet remains usable without the bridge */ }
    }

    const STATUS_LABELS = {
      idle: '空闲',
      running: '运行中',
      waiting: '等待中',
      failed: '出错了',
      review: '审查中',
    }

    function taskLabel(task) {
      if (typeof task !== 'string') return ''
      const value = task.trim()
      if (!value) return ''
      return value.length > 28 ? `${value.slice(0, 28)}…` : value
    }

    /*
     * Desktop-only variant: the Python overlay owns all pet visuals and input.
     * Do not mount a second pet inside the DSH window.
     */
    function PetRoot() {
      return null
    }

    function MenuItem({ onClick, children }) {
      return h('button', {
        type: 'button',
        onClick,
        onMouseEnter: (event) => { event.currentTarget.style.background = 'rgba(255,255,255,0.10)' },
        onMouseLeave: (event) => { event.currentTarget.style.background = 'transparent' },
        style: {
          appearance: 'none',
          border: 'none',
          borderRadius: 6,
          background: 'transparent',
          color: 'inherit',
          font: 'inherit',
          textAlign: 'left',
          padding: '6px 10px',
          cursor: 'pointer',
        },
      }, children)
    }

    function PetSprite({ onOpenMenu }) {
      const [status, setStatus] = useState('idle')
      const [task, setTask] = useState('')
      const [position, setPosition] = useState(readStoredPosition)
      const [frame, setFrame] = useState(0)
      const dragRef = useRef(null)

      useEffect(() => watchAgentState((data) => {
        if (typeof data.status === 'string') setStatus(data.status)
        if (typeof data.task === 'string') setTask(data.task)
      }), [])

      const row = rowForStatus(status)
      const rowIndex = ROW_INDEX[row]
      const rowFrames = ROWS[rowIndex].frames

      useEffect(() => {
        setFrame(0)
      }, [row])

      useEffect(() => {
        const timer = setInterval(() => {
          setFrame((current) => (current + 1) % rowFrames)
        }, FRAME_MS[row] || 200)
        return () => clearInterval(timer)
      }, [row, rowFrames])

      const onPointerDown = useCallback((event) => {
        if (event.button !== 0) return
        const rect = event.currentTarget.getBoundingClientRect()
        dragRef.current = {
          offsetX: event.clientX - rect.left,
          offsetY: event.clientY - rect.top,
        }
        event.currentTarget.setPointerCapture(event.pointerId)
      }, [])

      const onPointerMove = useCallback((event) => {
        const drag = dragRef.current
        if (!drag) return
        setPosition({
          left: Math.max(0, Math.min(window.innerWidth - DISP_W, event.clientX - drag.offsetX)),
          top: Math.max(0, Math.min(window.innerHeight - DISP_H, event.clientY - drag.offsetY)),
        })
      }, [])

      const onPointerUp = useCallback((event) => {
        if (!dragRef.current) return
        dragRef.current = null
        try { event.currentTarget.releasePointerCapture(event.pointerId) } catch { /* already released */ }
        setPosition((current) => {
          if (current) store(POSITION_KEY, JSON.stringify(current))
          return current
        })
      }, [])

      const placement = position
        ? { left: position.left, top: position.top, right: 'auto', bottom: 'auto' }
        : { right: 16, bottom: 16 }

      const spriteStyle = {
        width: DISP_W,
        height: DISP_H,
        backgroundImage: `url("${endpoint(SPRITE_ROUTE)}")`,
        backgroundRepeat: 'no-repeat',
        backgroundSize: `${CELL_W * 8 * SCALE}px ${CELL_H * 9 * SCALE}px`,
        backgroundPosition: `${-frame * DISP_W}px ${-rowIndex * DISP_H}px`,
        imageRendering: 'pixelated',
        filter: 'drop-shadow(0 4px 6px rgba(0,0,0,0.25))',
        pointerEvents: 'none',
      }

      return h('div', {
        'data-dsh-pet-gujiguji': '',
        title: taskLabel(task)
          ? `GujiGuji · ${status} · ${taskLabel(task)}（拖拽移动，右键隐藏）`
          : `GujiGuji · ${status}（拖拽移动，右键隐藏）`,
        'aria-label': `GujiGuji desktop pet: ${status}${taskLabel(task) ? `, ${taskLabel(task)}` : ''}`,
        role: 'img',
        onPointerDown,
        onPointerMove,
        onPointerUp,
        onPointerCancel: onPointerUp,
        onContextMenu: onOpenMenu,
        style: {
          position: 'fixed',
          zIndex: 2147483646,
          cursor: 'grab',
          touchAction: 'none',
          userSelect: 'none',
          ...placement,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          gap: 4,
          padding: '4px 6px',
          borderRadius: 10,
          background: 'rgba(20,28,40,0.55)',
          backdropFilter: 'blur(6px)',
          boxShadow: '0 6px 16px rgba(0,0,0,0.25)',
        },
      }, h('div', { style: spriteStyle }), h('div', {
        style: {
          color: '#e6f0ff',
          fontSize: 11,
          lineHeight: '14px',
          fontFamily: 'system-ui, -apple-system, Segoe UI, Roboto, sans-serif',
          whiteSpace: 'nowrap',
          pointerEvents: 'none',
          textShadow: '0 1px 2px rgba(0,0,0,0.4)',
        },
      }, taskLabel(task)
        ? `${STATUS_LABELS[status] || status} · ${taskLabel(task)}`
        : (STATUS_LABELS[status] || status)))
    }

    return {
      // The desktop-only build intentionally does not register a dsh slot.
      // Keeping the module loadable avoids breaking an older profile while
      // the desktop overlay handles all rendering.
      inject: [],
      apply() {},
    }
  },
})
