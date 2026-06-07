const vm = require('vm');
const fs = require('fs');

const code = fs.readFileSync('C:\\_C_\\Users\\hianime\\e1-player.min.js', 'utf8');

let captured = null;

function makeEval(ctx) {
    return function customEval(source) {
        if (typeof source !== 'string') return source;
        if (source.includes('function EXIr')) {
            // outer eval - run EXIr definition + invocation
            return vm.runInContext(source, ctx);
        }
        if (source.length > 200) {
            // inner eval - this is the decrypted payload
            captured = source;
            // throw so execution stops cleanly
            throw new Error('__CAPTURED__');
        }
        try { return vm.runInContext(source, ctx); } catch(e) { return undefined; }
    };
}

const ctx = vm.createContext({
    Array, Object, String, Number, Boolean, Math, Date,
    Error, SyntaxError, TypeError, RangeError,
    Function, RegExp, JSON,
    parseInt, parseFloat, isNaN, isFinite,
    decodeURI, decodeURIComponent, encodeURI, encodeURIComponent,
    URLSearchParams: class { constructor(s){ this._s=s||''; } get(k){ return null; } },
    console,
    setTimeout: ()=>{}, clearTimeout: ()=>{}, setInterval: ()=>{}, clearInterval: ()=>{},
    fetch: ()=>Promise.resolve({text:()=>Promise.resolve('[]'),json:()=>Promise.resolve({})}),
    window: { location: { search: '', href: '', replace: ()=>{} }, addEventListener: ()=>{} },
    document: { getElementById: ()=>null, querySelectorAll: ()=>[], addEventListener: ()=>{},
                 write: ()=>{}, createElement: ()=>({style:{}, appendChild:()=>{}}),
                 body: { appendChild:()=>{} } },
    navigator: { userAgent: 'Mozilla/5.0' },
});
ctx.self = ctx.window;
ctx.eval = makeEval(ctx);
ctx.globalThis = ctx;

try {
    vm.runInContext(code, ctx);
} catch(e) {
    if (e.message !== '__CAPTURED__') {
        // might be OK, EXIr re-throws after we capture
    }
}

if (captured) {
    fs.writeFileSync('C:\\_C_\\Users\\hianime\\e1-decrypted.js', captured, 'utf8');
    console.log('[+] Captured decrypted code, length:', captured.length);
    console.log('[+] Saved to e1-decrypted.js');
    console.log('[+] First 300 chars:', captured.substring(0, 300));
} else {
    console.log('[-] Nothing captured. evalCallCount check needed.');
}
