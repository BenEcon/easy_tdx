# TDX 协议逆向工程全景

本文记录通达信 (TDX) 私有二进制 TCP 协议的逆向研究过程，帮助理解 easy-tdx 项目中各层协议实现的设计原理。

## 第一层：抓包 — 发现帧结构

通达信客户端和服务器之间是裸 TCP（端口 `7709`），没有 HTTP 包装。研究者通过 Wireshark 抓包发现了一个固定的帧格式：

```
响应帧 = 16字节固定头 + 可变长度 body
```

`codec/frame.py` 记录了这个发现：

```
偏移  0: I (4字节) — 未知
偏移  4: I (4字节) — 未知
偏移  8: I (4字节) — 未知
偏移 12: H (2字节) — zipsize（body 实际长度）
偏移 14: H (2字节) — unzipsize（解压后长度）
```

关键发现：**当 zipsize == unzipsize 时 body 未压缩，否则需要 zlib 解压**。这是通过对比抓包数据和 zlib 解压结果验证的。

## 第二层：握手 — 三条神秘命令

`commands/setup.py` 中的三条握手命令是硬编码的原始字节：

```python
SETUP_CMD1: "0c0218930001030003000d0001"
SETUP_CMD2: "0c0218940001030003000d0002"
SETUP_CMD3: "0c031899000120002000db0f..."  # 30字节，含GBK编码的"申银万国"
```

注释写得很清楚："从 pytdx 源码移植，已在真实服务器验证"。这说明握手命令不是这个项目原创的，而是从开源项目 [pytdx](https://github.com/rainx/pytdx) 继承来的。pytdx 的作者 rainx 通过**逆向通达信 Windows 客户端**（用 IDA Pro 等反汇编工具）得到了这些字节序列。

第三条命令特别有意思，里面包含了 `d5d0c9ccd6a4a8af`，这是 GBK 编码的"申银万国"（一家券商名），说明这条握手命令里包含了**客户端标识信息**。

## 第三层：请求构造 — 猜解命令格式

每个命令的请求都是一个固定格式的二进制包。以 `security_list.py` 为例：

```python
header = bytes.fromhex("0c0118640101060006005004")
payload = struct.pack("<HHH", market, start, 0)
```

这些 magic number（如 `0c0118640101060006005004`）是怎么来的？有两种途径：

1. **反汇编客户端**：在通达信的 exe/dll 中找到构建这些请求包的函数
2. **协议模糊测试**：修改已知命令的某些字节，观察服务器响应变化

比如 K 线命令 `security_bars.py` 的头部：

```python
struct.pack("<HIHHHH6sHHHHIIH",
    0x010C,       # 固定魔数
    0x01016408,   # 命令 ID（K线数据的标识）
    0x001C,       # payload 长度 = 28
    0x001C,       # 重复的 payload 长度
    0x052D,       # 子命令/协议版本
    market,       # 市场
    code,         # 股票代码（6字节）
    category,     # K线周期
    1,            # 未知，可能是数据类型
    start,        # 起始位置
    count,        # 请求数量
    0, 0, 0,      # 三个保留字段
)
```

通过逐个修改这些字段发送给服务器，观察返回数据的变化，就能推断每个字段的含义。

## 第四层：响应解析 — 最难的部分

响应的解析才是真正的逆向难点。以实时行情 (`security_quotes.py`) 为例：

**差分编码**：服务器返回的不是绝对价格，而是差值（delta）。所有价格字段都是相对于 `price_raw` 的差分：

```python
pre_close = (price_raw + last_close_diff) / 100.0
open      = (price_raw + open_diff) / 100.0
high      = (price_raw + high_diff) / 100.0
# 五档买卖也是差分：
bid1 = (price_raw + bid1_d) / 100.0
```

K 线数据更复杂，使用了累积差分 (`security_bars.py`)：

```python
open_abs  = open_diff + pre_diff_base
close_abs = open_abs + close_diff
high_abs  = open_abs + high_diff
low_abs   = open_abs + low_diff
pre_diff_base = open_abs + close_diff  # 下一根K线的基准
```

## 第五层：编解码 — 自定义数据格式

### 价格编码 (`codec/price.py`) — 类 LEB128 变长有符号整数

```
首字节: [bit7=继续][bit6=符号][bit5-0=低6位数据]
后续字节: [bit7=继续][bit6-0=7位数据]
```

这不是标准 LEB128，而是通达信自己的变体。推断过程：

1. 抓包看到价格附近的数据长度不固定（1-4字节）
2. 注意到 bit7 似乎是"还有更多字节"的标记
3. 发现 bit6 是符号位
4. 通过已知价格验证：发送请求时知道某个价格是 15.50，在响应中找到对应的字节序列，反推编码规则

### 成交量编码 (`codec/volume.py`) — 完全自定义的 4 字节浮点

```python
logpoint = (ivol >> 24) & 0xFF   # 指数
hleax    = (ivol >> 16) & 0xFF   # 高精度
lheax    = (ivol >> 8) & 0xFF    # 中精度
lleax    = ivol & 0xFF           # 低精度
```

这个格式完全不是 IEEE 754，是通达信自创的。逆向方法：拿到已知成交量的 hex dump，用不同的拆分方式穷举，直到找到能还原正确数值的公式。

## 第六层：未知字段 — 逆向的痕迹

代码中大量保留了 `unknown_0` 到 `unknown_8` 的字段，这本身就是逆向过程的痕迹——解析出格式但不确定含义的字段。比如：

- `unknown_0` 后来被发现是服务器时间戳（"小时 + 百万分之一小时"编码）
- `unknown_1` 推测等于 `-price_raw`
- 指数 K 线比股票 K 线多 4 字节（上涨/下跌家数），是通过对比同一市场的指数和股票响应长度差异发现的

## 总结：逆向方法论

这个项目体现的逆向研究路线是：

1. **抓包** (Wireshark) → 发现 TCP 帧结构、握手序列
2. **反汇编** (IDA Pro) → 得到请求构造函数、编解码算法
3. **黑盒验证** → 修改参数发请求，对比响应确认字段含义
4. **差分分析** → 利用已知数据（如已知价格）反推编码公式
5. **对比分析** → 指数 vs 股票、不同市场、不同周期的响应差异
6. **开源传承** → pytdx 打下基础，easy-tdx 在此之上修复 bug 并重构

核心依赖是 **pytdx 项目**做的基础逆向工作（反汇编通达信客户端），easy-tdx 则是在已有协议知识上的高质量 Python 重写。
