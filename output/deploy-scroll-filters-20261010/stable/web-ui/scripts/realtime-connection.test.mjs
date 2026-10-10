import { test } from 'node:test'
import assert from 'node:assert/strict'
import { bindRealtimeSocket } from '../src/realtime-connection.ts'

test('late messages, close and errors from an old socket cannot affect replacement', () => {
  const old = {}, replacement = {}, events = []
  let current = old
  const handlers = {connected:()=>events.push('open'),tick:v=>events.push(v),error:e=>events.push(e),closed:e=>events.push(e)}
  bindRealtimeSocket(old, () => current === old, handlers)
  old.onopen()
  current = replacement
  bindRealtimeSocket(replacement, () => current === replacement, handlers)
  old.onmessage({data:'{"type":"tick","code":"000001"}'})
  old.onclose({code:4429})
  old.onerror()
  old.onopen()
  replacement.onmessage({data:'{"type":"tick","code":"300750"}'})
  assert.deepEqual(events, ['open', {type:'tick',code:'300750'}])
})

test('invalid messages and control responses never become ticks; close reason retained', () => {
  const socket = {}, ticks = [], errors = [], closes = []
  bindRealtimeSocket(socket, () => true, {connected:()=>{},tick:v=>ticks.push(v),error:e=>errors.push(e),closed:e=>closes.push(e)})
  for (const data of ['null','[]','bad','{"type":"ping"}','{"type":"status"}']) socket.onmessage({data})
  socket.onmessage({data:'{"type":"error","msg":"超出订阅数"}'})
  socket.onclose({code:4429,reason:'连接数已达上限'})
  assert.equal(ticks.length, 0)
  assert.equal(errors.length, 4)
  assert.equal(errors.at(-1), '超出订阅数')
  assert.deepEqual(closes, [{code:4429,reason:'连接数已达上限'}])
})
