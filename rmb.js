// 数字金额转人民币大写(依据《会计基础工作规范》:到元或角为止写"整",到分不写"整")
function rmbUpper(input) {
  var s = String(input).trim().replace(/,/g, '');
  if (!/^\d+(\.\d{0,2})?$/.test(s)) return '';
  var parts = s.split('.'), intPart = parts[0].replace(/^0+(?=\d)/, ''), dec = ((parts[1] || '') + '00').slice(0, 2);
  if (intPart.length > 16) return '';
  var D = '零壹贰叁肆伍陆柒捌玖', U = ['', '拾', '佰', '仟'], G = ['', '万', '亿', '万亿'];
  var out = '', zero = false, n = intPart.length;
  for (var i = 0; i < n; i++) {
    var d = +intPart[i], pos = n - 1 - i, u = pos % 4, g = Math.floor(pos / 4);
    if (d === 0) { zero = true; }
    else { if (zero && out) out += '零'; zero = false; out += D[d] + U[u]; }
    if (u === 0 && g > 0) {
      var grp = intPart.slice(Math.max(0, i - 3), i + 1);
      if (+grp > 0) { out += G[g]; zero = false; }  // 新的一组从头开始,只有该组开头有 0 时才补"零"
    }
  }
  var jiao = +dec[0], fen = +dec[1], res = '';
  if (out) res = out + '元';
  if (jiao === 0 && fen === 0) return (res || '零元') + '整';
  if (jiao > 0) res += D[jiao] + '角';
  else if (res) res += '零';
  if (fen > 0) res += D[fen] + '分'; else res += '整';
  return res;
}
if (typeof module !== 'undefined') module.exports = rmbUpper;
