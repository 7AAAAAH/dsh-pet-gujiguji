import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import { name } from '../index.js'


const ROOT = dirname(dirname(fileURLToPath(import.meta.url)))
const packageJson = JSON.parse(readFileSync(join(ROOT, 'package.json'), 'utf8'))
const client = readFileSync(join(ROOT, 'client.js'), 'utf8')
const cordis = readFileSync(join(ROOT, 'cordis.patch.yml'), 'utf8')


test('package, Cordis plugin, and client share the public identity', () => {
  assert.equal(packageJson.name, 'dsh-pet-gujiguji')
  assert.equal(name, 'dsh-pet-gujiguji')
  assert.match(cordis, /id: dsh-pet-gujiguji/)
  assert.match(client, /id: 'dsh-pet-gujiguji'/)
})


test('the packaged desktop executable uses the new name', () => {
  assert.ok(packageJson.files.includes('desktop/dsh-pet-gujiguji-*.exe'))
  assert.ok(existsSync(join(ROOT, 'desktop', 'dsh-pet-gujiguji.spec')))
})
