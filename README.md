# 项目名称

简要介绍项目功能：  
这是一个基于 FastAPI 的链端接口服务，封装了统一 HTTP 接口、日志记录和链端命令执行。

---

## 环境准备

1. **Python 版本**：建议使用 Python >=3.12.3
2. **创建虚拟环境（推荐）**：

```bash
# Linux / macOS
python3 -m venv venv
source venv/bin/activate

# Windows
python -m venv venv
venv\Scripts\activate
```

3. **安装依赖**：
`pip install -r requirements.txt`

## 启动 FastAPI 服务
```bash
# 启动服务
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

## API调用示例

1️⃣ 查询链节点状态（非多签示例）

发送 POST 请求到 /gead/status，可以查询链节点状态和基础信息。

```bash
curl --location --request POST 'http://localhost:8000/gead/status' \
--header 'X-Env-Use-Multisig: true' \
--header 'X-Use-Multisig: false' \
--header 'X-Multisig-Signers: u1,u2,u3' \
--header 'X-Multisig-Name: global_dao' \
--form 'node="http://118.175.0.254:26657"' \
--form 'home="/home/lino/.gea_uat"'
```

参数说明：

| 参数                   | 说明                   |
| -------------------- | -------------------- |
| `X-Env-Use-Multisig` | 是否启用多签环境（true/false） |
| `X-Use-Multisig`     | 当前请求是否使用多签           |
| `X-Multisig-Signers` | 多签账户列表，用逗号分隔         |
| `X-Multisig-Name`    | 多签账户名称               |
| `node`               | 链节点 RPC 地址           |
| `home`               | 本地配置目录               |


2️⃣ 存入邀请奖励池（多签示例）

发送 POST 请求到 /gead/tx/staking/deposit-to-invitation-reward-pool，将指定金额存入邀请奖励池。

```bash
curl --location --request POST 'http://localhost:8000/gead/tx/staking/deposit-to-invitation-reward-pool?region-id=afg&amount=100000000ugea' \
--header 'X-Env-Use-Multisig: true' \
--header 'X-Use-Multisig: true' \
--header 'X-Multisig-Signers: u1,u2,u3' \
--header 'X-Multisig-Name: global_dao' \
--form 'from="gea1rlgwy4q58yr7kyqkm7rc4wvnyvqvuj3k36k09c"' \
--form 'fees="40000ugea"' \
--form 'gas="400000"' \
--form 'chain-id="gea_20-1"' \
--form 'node="http://118.175.0.254:26657"' \
--form 'keyring-backend="test"' \
--form 'home="/home/lino/.gea_uat"' \
--form 'yes=""'

```

参数说明：

| 参数          | 说明                           |
| ----------- | ---------------------------- |
| `region-id` | 奖励池所属区域 ID                   |
| `amount`    | 存入金额及代币单位，例如 `100000000ugea` |
| `from`      | 交易发起账户地址                     |
| `fees`      | 手续费金额                        |
| `gas`       | Gas 限额                       |
| `chain-id`  | 链 ID                         |
| 其他参数        | 与多签和节点配置相关，说明同上              |


## Query Parameters 参数说明

| 参数名称 | 类型 | 必填 | 默认值 | 说明 |
|----------|------|------|--------|------|
| `region-id` | string | 否 | `afg` | 国家/区域 ID，用于标识交易所属区域 |
| `amount` | string | 否 | `100000000ugea` | 金额，单位可为 `gea` 或 `ugea` |


## Form-Data 参数说明

| 参数名称 | 类型 | 必填 | 默认值 | 说明 |
|----------|------|------|--------|------|
| `from` | string | 否 | `gea1rlgwy4q58yr7kyqkm7rc4wvnyvqvuj3k36k09c` | 签名地址，例如：`global_dao` |
| `fees` | string | 否 | `40000ugea` | 手续费，单位：`gea` 或 `ugea` |
| `gas` | string | 否 | `400000` | Gas 上限 |
| `chain-id` | string | 否 | `gea_20-1` | 链 ID |
| `node` | string | 否 | `http://118.175.0.254:26657` | 节点 RPC 地址 |
| `keyring-backend` | string | 否 | `test` | 私钥存储方式，例如：`test` / `os` / `file` |
| `home` | string | 否 | `/home/lino/.gea_uat` | 本地配置和数据目录 |
| `yes` | string | 否 |  | 是否自动确认（可为空，表示默认行为） |


## 请求头参数说明（多签相关）

| 请求头名称 | 类型 | 必填 | 默认值 | 说明 |
|------------|------|------|--------|------|
| `X-Env-Use-Multisig` | string | 否 | `{{X-Env-Use-Multisig}}` | 是否启用多签环境开关；可选 `true` / `false`。用于区分不同环境（如本地环境不多签，UAT 环境多签）。 |
| `X-Use-Multisig` | string | 否 | `false` | 当前命令是否启用多签；只有当 `X-Env-Use-Multisig=true` 且 `X-Use-Multisig=true` 时，接口才执行多签逻辑。 |
| `X-Multisig-Signers` | string | 否 | `{{X-Multisig-Signers}}` | 多签参与者名称列表，用逗号分隔，例如：`u1,u2,u3`。 |
| `X-Multisig-Name` | string | 否 | `{{X-Multisig-Name}}` | 合并签名时使用的多签账户名称，例如：`global_dao`。 |


## 作者与联系方式

- **作者**：Lino  
- **邮箱**：lino@example.com  
- **GitHub**：
- **项目支持**：如有问题或建议，请通过邮箱或 GitHub 提交 issue  


## 说明

1. 欢迎在遵守开源协议的前提下使用和扩展本项目。  
2. 仅用于技术交流和问题反馈，请勿用于其他用途。