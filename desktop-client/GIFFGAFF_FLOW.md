# giffgaff 激活流程记录

记录日期：2026-06-20

## 固定业务规则

- 只使用 `Pay as you go / No monthly plan`
- 充值金额固定选择 `£10`
- 密码随机生成，但必须满足 giffgaff 规则并保存到后台/客户端，后续登录会用到
- 开户姓名、英国地址、支付卡由客户端本机预设自动填写
- 支付卡填入后停止在 `Place order` 前，由人工完成付款/3DS
- 付款完成后客户端自动打开支付方式页并移除保存的信用卡

## 页面步骤

1. `/activate`
   - 标题：`Let's activate your SIM`
   - 填写 SIM activation code
   - 点击 `Activate your SIM`

2. `/auth/register`
   - 标题：`What’s your email address?`
   - 填写 `Your email`
   - 点击 `Next`

3. `/auth/register/validate-email`
   - 标题：`Confirm your email`
   - 填写 6 位邮箱验证码
   - 点击 `Confirm`

4. `/auth/register/password`
   - 标题：`Create a password`
   - 密码规则：
     - uppercase letter
     - lowercase letter
     - number or special character
     - at least 12 characters
   - 填写后台生成的 `initial_password`
   - 点击 `Register`

5. `/auth/register/stay_in_touch`
   - 标题：`Let's stay in touch`
   - 选择 `No, thanks`
   - `Year of birth` 可留空
   - 点击 `Continue`

6. `/activate` 套餐页
   - 标题：`Choose a monthly plan`
   - 滚动到 `Other options`
   - 选择 `Pay as you go / No monthly plan`
   - 点击 `Continue`

7. `/activate` 充值页
   - 标题：`Add credit`
   - 选择 `£10`
   - 点击 `Pay now`

8. `/activate` 开户详情页
   - 标题：`Your details`
   - 填写 `First name` / `Last name`
   - `Country` 保持 `United Kingdom`
   - 填写 `Postcode`
   - 等待 Loqate 地址候选列表
   - 选择配置中的候选序号，默认第 1 个
   - 必要时回填 `Address line 1` / `Address line 2` / `Town`
   - 点击 `Continue`

9. `/payments?sessionId=...`
   - 标题：`Payment`
   - 确认 `Total today £10`
   - 填写：
     - `Card number`
     - `Name on card`
     - `Expiry date`
     - `Security code`
   - 确认/勾选 `I understand and agree`
   - 停在 `Place order` 前，人工完成付款

10. `/profile/payment-details`
    - 标题：`Orders and payments`
    - 区块：`Payment Method`
    - 已保存卡入口：`Your credit/debit card`
    - 点击 `Remove this credit/debit card`
    - 确认弹窗：
      - 标题：`Are you sure you want to remove your card?`
      - 文案：删除会取消 auto-renewing plan 或 auto top up 设置；以后保存卡需重新输入
      - 点击 `Yes, remove it`

