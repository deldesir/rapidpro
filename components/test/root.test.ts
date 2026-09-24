import { expect } from '@open-wc/testing';
import { getAppRoot, rootUrl } from '../src/root';

describe('app root', () => {
  afterEach(() => {
    delete (window as any).URLS;
  });

  it('defaults to the root and leaves urls alone', () => {
    expect(getAppRoot()).to.equal('/');
    expect(rootUrl('/api/v2/contacts.json')).to.equal('/api/v2/contacts.json');
  });

  it('prefixes root-absolute app paths with the published root', () => {
    (window as any).URLS = { root: '/rp/' };
    expect(getAppRoot()).to.equal('/rp/');
    expect(rootUrl('/api/v2/contacts.json')).to.equal(
      '/rp/api/v2/contacts.json'
    );
    expect(rootUrl('/ticket/folder/mine/')).to.equal('/rp/ticket/folder/mine/');
  });

  it('accepts a root without a trailing slash', () => {
    (window as any).URLS = { root: '/rp' };
    expect(rootUrl('/msg/inbox/')).to.equal('/rp/msg/inbox/');
  });

  it('never prefixes twice, nor absolute or relative urls', () => {
    (window as any).URLS = { root: '/rp/' };
    expect(rootUrl('/rp/api/v2/contacts.json')).to.equal(
      '/rp/api/v2/contacts.json'
    );
    expect(
      rootUrl('https://example.com/rp/api/v2/contacts.json?cursor=x')
    ).to.equal('https://example.com/rp/api/v2/contacts.json?cursor=x');
    expect(rootUrl('//example.com/x')).to.equal('//example.com/x');
    expect(rootUrl('contacts.json')).to.equal('contacts.json');
    expect(rootUrl('')).to.equal('');
  });
});
