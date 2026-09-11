import test from 'node:test';
import assert from 'node:assert/strict';
import { getAuth, createModifyCardAction, createRemoveCardAction } from '../utils/archidekt.js';

test('injected login is reused and renewed before expiry', async () => {
  const originalFetch = globalThis.fetch;
  const originalNow = Date.now;
  const originalEnv = { ...process.env };
  let now = 1_800_000_000_000;
  let logins = 0;
  Date.now = () => now;
  process.env.ARCHIDEKT_USERNAME = 'test-user';
  process.env.ARCHIDEKT_PASSWORD = 'test-password';
  globalThis.fetch = async (url, options) => {
    assert.equal(url, 'https://archidekt.com/api/rest-auth/login/');
    assert.deepEqual(JSON.parse(options.body), {username: 'test-user', password: 'test-password'});
    logins++;
    return Response.json({access_token: `test-token-${logins}`, refresh_token: 'refresh',
      user: {id: 1, rootFolder: 2, username: 'test-user'}});
  };
  try {
    assert.equal((await getAuth()).accessToken, 'test-token-1');
    now += 54 * 60 * 1000;
    assert.equal((await getAuth()).accessToken, 'test-token-1');
    assert.equal(logins, 1);
    now += 7 * 60 * 1000;
    assert.equal((await getAuth()).accessToken, 'test-token-2');
    assert.equal(logins, 2);
  } finally {
    globalThis.fetch = originalFetch;
    Date.now = originalNow;
    process.env = originalEnv;
  }
});

test('partial stack edits preserve deck relation and categories', () => {
  const options = {cardId: '12', deckRelationId: '34', quantity: 2, categories: ['Land']};
  const modify = createModifyCardAction(options);
  assert.equal(modify.action, 'modify');
  assert.equal(modify.deckRelationId, '34');
  assert.equal(modify.modifications.quantity, 2);
  assert.deepEqual(modify.categories, ['Land']);
  assert.equal(createRemoveCardAction(options).action, 'remove');
});
