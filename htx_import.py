"""Read-only HTX order import into a local portfolio backup. No trading."""
import argparse, base64, datetime as dt, hashlib, hmac, json, os, sys
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlencode, quote
from urllib.request import urlopen
HOST='api.huobi.pro'
ASSETS={'BTC','ETH','SOL','GRAM','ZRO'}
def request(path, params, key=None, secret=None):
    params=dict(params)
    if key:
        params.update(AccessKeyId=key, SignatureMethod='HmacSHA256',SignatureVersion='2',Timestamp=dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S'))
        encoded=urlencode(sorted(params.items()),quote_via=quote)
        signature=hmac.new(secret.encode(),f'GET\n{HOST}\n{path}\n{encoded}'.encode(),hashlib.sha256).digest()
        params['Signature']=base64.b64encode(signature).decode()
    with urlopen(f'https://{HOST}{path}?{urlencode(params,quote_via=quote)}',timeout=20) as response:
        result=json.load(response)
    if result.get('status')!='ok': raise RuntimeError(f"HTX error: {result.get('err-code','unknown')}")
    return result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('backup',type=Path); p.add_argument('output',type=Path); p.add_argument('--order',action='append',default=[]); p.add_argument('--quotes',action='store_true')
    a=p.parse_args(); s=json.loads(a.backup.read_text()); key=os.getenv('HTX_ACCESS_KEY'); secret=os.getenv('HTX_SECRET_KEY')
    if a.order and not(key and secret): p.error('Set HTX_ACCESS_KEY and HTX_SECRET_KEY locally (read-only).')
    for oid in a.order:
        if not oid.isdigit(): p.error('Order IDs must be digits')
        rows=request(f'/v1/order/orders/{oid}/matchresults',{},key,secret)['data']; converted=[]
        if not rows: raise RuntimeError('No fills returned; backup not changed')
        for r in rows:
            sym=r['symbol'].upper(); asset=sym[:-4]
            if not sym.endswith('USDT') or asset not in ASSETS: raise RuntimeError(f'Unsupported symbol {sym}')
            qty=Decimal(r['filled-amount']); price=Decimal(r['price']); fee=Decimal(r['filled-fees']); fee_coin=r.get('fee-currency','').upper(); side=r['type'].split('-')[0]
            if side not in ('buy','sell') or fee<0 or (fee and fee_coin not in (asset,'USDT')) or Decimal(r.get('filled-points') or '0')!=0: raise RuntimeError('Unsupported fee or order type; review manually')
            converted.append(dict(id='htx-fill-'+str(r['id']),orderId=oid,type=side,exchange='HTX',asset=asset,date=dt.datetime.fromtimestamp(r['created-at']/1000,dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%S'),qty=float(qty),amount=float(qty*price),fee=float(fee),feeCoin=fee_coin or asset,note='HTX API, UTC'))
        s['tx']=[t for t in s['tx'] if not(t.get('exchange')=='HTX' and (t.get('id')=='htx-'+oid or t.get('orderId')==oid))]+converted
    if a.quotes:
        for asset in sorted(ASSETS):
            try:
                tick=request('/market/detail/merged',{'symbol':asset.lower()+'usdt'})['tick']; s['quotes'][asset]={'now':tick['close'],'prev':None}
            except Exception as e: print(f'{asset}: quote unavailable ({type(e).__name__})',file=sys.stderr)
        print('24-hour exact reference and RUB rates remain manual.',file=sys.stderr)
    if a.output.resolve()==a.backup.resolve(): p.error('Output must differ from backup')
    a.output.write_text(json.dumps(s,ensure_ascii=False,indent=2)); print('Saved',a.output)
if __name__=='__main__': main()
