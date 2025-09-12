# 项目名称

简要介绍项目功能：  
这是一个基于 FastAPI 的链端接口服务，封装了统一 HTTP 接口、日志记录和链端命令执行。


第二版
---

# 请求地址
http://localhost:8000

# 环境变量说明

| 参数名 | 类型 | 必填 | 默认值 | 示例 | 说明 |
|--------|------|------|--------|------|------|
| chain-id | string | true | gea_20-1 |  | 链ID |
| node | string | true | http://118.175.0.254:26657 |  | 节点 RPC 地址 |
| keyring-backend | string | true | test |  | 私钥存储方式 |
| home | string | true | /home/lino/.gea_uat |  | 本地配置和数据目录 |
| output | string | true | json |  | 输出格式 |
| EnvUseMultisig | boolean | true | true |  | 是否启用多签；true/false |
| MultisigSigners | string | true | "u1,u2,u3" |  | 多签签名的密钥名称，用于 `gead tx sign` |
| MultisigName | string | true | global_dao |  | 合并签名时使用的 key 名称，用于 `gead tx multisign` |
| MultisigAddress | string | true | gea1rlgwy4q58yr7kyqkm7rc4wvnyvqvuj3k36k09c |  | 多签签名地址，对应 `MultisigName` 的地址 |




## 多签前置脚本
```js
// ======================================================
// Pre-request Script: 多签开关判断
// ======================================================

// ---------------------------
// 1. 收集请求体中的 formdata 参数
// ---------------------------
const formData = {};
pm.request.body.formdata.all().forEach(item => {
    formData[item.key] = item.value;
});

// ---------------------------
// 2. 多签开关逻辑（最开始判断）
// ---------------------------
// 环境开关：环境配置是否启用多签
const EnvUseMultisig = pm.environment.get("EnvUseMultisig") === "true";
// 请求开关：是否在请求中带有 `generate-only=true`
const ReqUseMultisig = formData.hasOwnProperty("generate-only") && formData["generate-only"] === "true";
// 最终判断是否进入多签流程
const NeedMultisig = EnvUseMultisig && ReqUseMultisig;

// console.log("是否进入多签流程 NeedMultisig:", NeedMultisig);

// ---------------------------
// 3. 如果不需要多签 → 移除 generate-only 并退出
// ---------------------------
if (!NeedMultisig) {
    if (formData.hasOwnProperty("generate-only")) {
        delete formData["generate-only"];
        pm.request.body.formdata.remove("generate-only"); // 确保请求不带 generate-only
        console.log("已移除请求参数 generate-only，跳过多签逻辑");
    }
    // 停止后续 Pre-request 脚本或测试脚本的多签执行逻辑
    pm.environment.set("NeedMultisig", "false");
} else {
    pm.environment.set("NeedMultisig", "true");
}

```


## 多签后置脚本
```js
// ======================================================
// 多签交易流程脚本（Postman Pre-request / Tests 中使用）
// ======================================================
// 1. 判断是否需要多签
const NeedMultisig = pm.environment.get("NeedMultisig");
if (NeedMultisig === undefined || NeedMultisig.toLowerCase() === "false") {
    console.log("多签流程被跳过，因为 NeedMultisig = false 或未设置");
    return; // 直接退出脚本，不执行后续多签操作
}
// ---------------------------
// 4. 获取环境变量（来自 Apifox / Postman 环境配置）
// ---------------------------
const env = pm.environment.toObject();
const uuid = "c52ab694-8ff5-4c40-b617-cbb3b373d5eb";
const targetUrl = env.BASE_URLS && env.BASE_URLS[uuid]; // 根据 UUID 获取前置 URL

// 常用参数
const chain_id        = env["chain-id"];
const node            = env["node"];
const home            = env["home"];
const keyring_backend = env["keyring-backend"];
const output          = env["output"];

// 多签相关参数
const MultisigAddress = env["MultisigAddress"];
const MultisigSigners = env["MultisigSigners"].split(","); // 多签签名人列表
const MultisigName    = env["MultisigName"];

// ---------------------------
// 5. 获取 transfer.json 数据（stdout）
// ---------------------------
let resJson = pm.response.json();
let transferJson = resJson.stdout; // 主交易 JSON 文件路径

// ---------------------------
// 6. 多签流程：签名、合并、广播
// ---------------------------
let signedTxs = []; // 保存各 signer 的签名文件路径

/**
 * 6.1 单个签名流程
 * @param {string} signer 签名人
 * @param {function} callback 回调函数
 */
function signTx(signer, callback) {
    const url = targetUrl + "/gead/tx/sign?fileName=" + encodeURIComponent(transferJson);

    pm.sendRequest({
        url: url,
        method: "POST",
        header: { "Content-Type": "application/x-www-form-urlencoded" },
        body: {
            mode: "formdata",
            formdata: [
                { key: "from", value: signer },
                { key: "multisig", value: MultisigAddress },
                { key: "chain-id", value: chain_id },
                { key: "node", value: node },
                { key: "home", value: home },
                { key: "keyring-backend", value: keyring_backend },
                { key: "output", value: output }
            ]
        }
    }, function(err, res) {
        if (err) {
            console.error(`签名失败: ${signer}`, err);
            return;
        }
        signedTxs.push(res.json().stdout); // 保存签名文件路径
        callback(); // 继续下一个 signer
    });
}

/**
 * 6.2 递归处理所有 signer
 * @param {number} index 当前 signer 索引
 */
function processSigners(index) {
    if (index >= MultisigSigners.length) {
        mergeMultisign(signedTxs); // 所有签名完成 → 合并多签
        return;
    }
    signTx(MultisigSigners[index], function() {
        processSigners(index + 1);
    });
}

/**
 * 6.3 合并多签交易
 * @param {string[]} fileList 所有签名文件路径
 */
function mergeMultisign(fileList) {
    const fileParams = fileList.map(f => "fileName=" + encodeURIComponent(f)).join("&");
    const url = targetUrl + "/gead/tx/multisign?tx=" 
              + encodeURIComponent(transferJson) 
              + "&MultisigName=" + MultisigName 
              + "&" + fileParams;

    pm.sendRequest({
        url: url,
        method: "POST",
        header: { "Content-Type": "application/x-www-form-urlencoded" },
        body: {
            mode: "formdata",
            formdata: [
                { key: "chain-id", value: chain_id },
                { key: "node", value: node },
                { key: "home", value: home },
                { key: "keyring-backend", value: keyring_backend },
                { key: "output", value: output }
            ]
        }
    }, function(err, res) {
        if (err) {
            console.error("合并多签失败", err);
            return;
        }
        broadcastTx(res.json().stdout); // 合并成功 → 广播
    });
}

/**
 * 6.4 广播最终交易
 * @param {string} mergedTxFile 合并后的交易文件路径
 */
function broadcastTx(mergedTxFile) {
    const url = targetUrl + "/gead/tx/broadcast?fileName=" + encodeURIComponent(mergedTxFile);

    pm.sendRequest({
        url: url,
        method: "POST",
        header: { "Content-Type": "application/x-www-form-urlencoded" },
        body: {
            mode: "formdata",
            formdata: [
                { key: "chain-id", value: chain_id },
                { key: "node", value: node },
                { key: "home", value: home },
                { key: "keyring-backend", value: keyring_backend },
                { key: "output", value: output }
            ]
        }
    }, function(err, res) {
        if (err) {
            console.error("广播交易失败", err);
            return;
        }

        // console.log("广播结果:", res.json());
    });
}

// ---------------------------
// 7. 启动多签签名流程
// ---------------------------
processSigners(0);


```




第一版
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