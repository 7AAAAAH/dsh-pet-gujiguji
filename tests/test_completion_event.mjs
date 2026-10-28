import assert from 'node:assert/strict'
import test from 'node:test'

import { isCompletedTurn } from '../index.js'


test('completed turns trigger the success reminder', () => {
  assert.equal(
    isCompletedTurn({
      type: 'turn/end',
      data: { reason: { kind: 'completed' } },
    }),
    true,
  )
  assert.equal(
    isCompletedTurn({
      type: 'turn/end',
      reason: 'completed',
    }),
    true,
  )
})


test('failed, interrupted, and unrelated events do not trigger it', () => {
  for (const kind of ['error', 'interrupted', 'max-tokens', 'cancelled']) {
    assert.equal(
      isCompletedTurn({
        type: 'turn/end',
        data: { reason: { kind } },
      }),
      false,
    )
  }
  assert.equal(
    isCompletedTurn({
      type: 'turn/start',
      data: { reason: { kind: 'completed' } },
    }),
    false,
  )
  assert.equal(isCompletedTurn(null), false)
})
