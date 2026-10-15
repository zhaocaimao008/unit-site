# 单位换算大全

全自动静态网站,推送代码后由 GitHub Actions 生成并发布到 GitHub Pages:
- 10 大类 77 种单位(含斤、两、亩、尺等市制单位)两两换算页,附换算器、公式、对照表
- 常用组合的数值页,如"100斤等于多少公斤""37摄氏度是多少华氏度"
- 各类别多单位同时换算器、数字转人民币大写(`rmb.js`)、BMI 计算器
- 英文版 `/en/`(`build_en.py`):英美常用单位(含杯、汤匙、英石等)换算页和数值页,与中文对应页互加 hreflang

换算系数均为标准定义值(`units.py`),用分数计算避免浮点误差。内容不依赖外部数据,无需定时更新。

## 本地测试

```bash
python3 build.py && python3 build_en.py && python3 validate_seo.py && python3 -m http.server -d dist
node -e "console.log(require('./rmb.js')('1234.56'))"
```
