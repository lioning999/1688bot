"""用 Qwen-Flash 跑 5 个 case 验证 Dario 方案：
规则出 tier + LLM 做异常检测 + 文案润色 + 工厂引导。

用法：cd src/api && python -X utf8 ../../tests/test_llm_verdict.py
"""
import asyncio, json, sys
from pathlib import Path

API_DIR = Path(__file__).resolve().parent.parent / "src" / "api"
sys.path.insert(0, str(API_DIR))

from adapters.qwen_adapter import QwenAdapter

# 5 个 case 的评估结果（规则引擎产出）
CASES = [
    {
        "name": "连衣裙",
        "price": "¥69.00", "moq": 1, "unit": "件",
        "title": "温柔初恋感白色吊带连衣裙女2025春新品海边渡假显瘦长裙",
        "supplier_name": "广州仟顺纺织有限公司",
        "supplier_location": "广州海珠区",
        "sold": 188, "repurchase": None, "positive_rate": None, "wantBuy": 231,
        "return7day": "OK", "service_labels": ["品质不符包赔", "7天无理由退货", "严选晚发必赔"],
        "seller_type": "normal", "factory_flags": "非生产厂家",
        "cert_type": "None", "shop_years": 2,
        "rule_tier": "watch_medium12", "rule_grade": "none", "rule_score": "9/18",
        "supplier_tier": "caution_weak2", "supplier_grade": "bad", "supplier_score": "4/9",
        "summary_tier": "wait_data",
        "rule_verdict": "观望。仅有1个维度有亮点——撑不起来。先收藏蹲数据，别急着下手。试错成本偏高（¥69.00/1件起），先算账再决定",
        "supplier_verdict": "谨慎。贸易商拿货，不是源头——价格有加价。没人验过厂——品质靠你自己判断——先比价再拿样，别急着批量",
    },
    {
        "name": "转转马",
        "price": "¥4.50", "moq": 1, "unit": "件",
        "title": "景德镇陶瓷转转小马旋转马有钱小摆件网红桌面装饰马年新年礼物",
        "supplier_name": "义乌市锂迪电子商务商行（个体工商户）",
        "supplier_location": "浙江金华",
        "sold": 5142, "repurchase": None, "positive_rate": None, "wantBuy": 3436,
        "return7day": "OK", "service_labels": ["7天无理由退货"],
        "seller_type": "normal", "factory_flags": "非生产厂家",
        "cert_type": "None", "shop_years": 2,
        "rule_tier": "go_hot_wanted", "rule_grade": "go", "rule_score": "12/18",
        "supplier_tier": "caution_weak2", "supplier_grade": "bad", "supplier_score": "4/9",
        "summary_tier": "conditional_supplier_weak",
        "rule_verdict": "值得做。卖得火（5142件）+ 当前热度高（3436人想看）——需求被两次验证过。试错成本极低（¥4.50/1件起），拿样基本不亏",
        "supplier_verdict": "谨慎。贸易商拿货，不是源头——价格有加价。没人验过厂——品质靠你自己判断——先比价再拿样，别急着批量",
    },
    {
        "name": "太阳镜",
        "price": "¥2.00", "moq": 2, "unit": "副",
        "title": "新款男士太阳镜高清变色偏光眼镜框防紫外线驾驶钓鱼墨镜厂家批发",
        "supplier_name": "台州市椒江宏欣眼镜有限公司",
        "supplier_location": "浙江台州",
        "sold": 8950, "repurchase": None, "positive_rate": None, "wantBuy": 169,
        "return7day": "NO", "service_labels": ["晚发必赔"],
        "seller_type": "shili", "factory_flags": "实力商家",
        "cert_type": "深度认证·tuv", "shop_years": 4,
        "rule_tier": "fatal_return", "rule_grade": "bad", "rule_score": "0/18",
        "supplier_tier": "trust_strong2", "supplier_grade": "go", "supplier_score": "9/9",
        "summary_tier": "no_product_fatal",
        "rule_verdict": "不建议。商品不支持7天无理由退货——消费者没有后悔药，退货纠纷风险高",
        "supplier_verdict": "可信。实力商家——有实体可追溯。TUV认证——有第三方背书。干了4年——能活下来的不会太差。拿样确认款式，可放心合作",
    },
    {
        "name": "唇釉",
        "price": "¥3.80", "moq": 1, "unit": "件",
        "title": "kakashow蝴蝶结双头唇釉哑光口红镜面丝绒柔雾水光嘟嘟唇跨境美妆",
        "supplier_name": "广州卡卡秀化妆品有限公司",
        "supplier_location": "广东广州",
        "sold": 0, "repurchase": 68.0, "positive_rate": None, "wantBuy": None,
        "return7day": "OK", "service_labels": ["7天无理由退货", "晚发必赔", "假一赔四"],
        "seller_type": "super_factory", "factory_flags": "超级工厂",
        "cert_type": "intertek", "shop_years": 10,
        "rule_tier": "caution_rep_low", "rule_grade": "bad", "rule_score": "10/18",
        "supplier_tier": "trust_strong2", "supplier_grade": "go", "supplier_score": "8/9",
        "summary_tier": "conditional_factory_strong",
        "rule_verdict": "谨慎。复购高（68.0%）但销量少（0件）——复购好但客户群还小。先拿样测需求。试错成本极低（¥3.80/1件起），拿样基本不亏",
        "supplier_verdict": "可信。超级工厂——有实体可追溯。intertek认证——有第三方背书。干了10年——能活下来的不会太差。拿样确认款式，可放心合作",
    },
    {
        "name": "手表",
        "price": "¥19.80-22.80", "moq": 1, "unit": "只",
        "title": "卡萨罗陀飞轮仿真机械钢带石英腕表 男士石英手表男批发",
        "supplier_name": "广州卡萨罗表业有限公司",
        "supplier_location": "广东广州",
        "sold": 0, "repurchase": None, "positive_rate": None, "wantBuy": 20,
        "return7day": "OK", "service_labels": ["7天无理由退货", "晚发必赔"],
        "seller_type": "normal_factory", "factory_flags": "工厂直供",
        "cert_type": "None", "shop_years": 1,
        "rule_tier": "watch_flat", "rule_grade": "none", "rule_score": "8/18",
        "supplier_tier": "usable_ok", "supplier_grade": "ok", "supplier_score": "5/9",
        "summary_tier": "wait_data",
        "rule_verdict": "观望。全维度平平——没看到足够亮点。先收藏蹲数据。试错成本极低（¥22.80/1件起），拿样基本不亏",
        "supplier_verdict": "可用。工厂直供——不是贸易商。没认证——中小工厂常态。刚干1年——还嫩。拿样验货后可考虑",
    },
]

SYSTEM_PROMPT = """你是 1688 跨境电商采购助手。你的任务是对给定的商品数据给出分析。

## 你的能力
1. **异常检测**：检查数据之间是否有矛盾。例如：复购率很高但销量为0→可能换品或刷单；销量巨大但关注很少→可能是老品尾货。
2. **工厂引导**：如果工厂数据很好（实力工厂+认证+多年）但产品数据可疑，建议用户去看工厂主页的其他产品。
3. **文案润色**：把模板化的判词改写成自然流畅的人话。保留所有关键数字。

## 输出格式（严格遵守，不要多余内容）
产品判词：<一句话，自然人话。包含关键数字。发现异常要指出>
供应商判词：<一句话，自然人话。试错成本低/高要提>
异常标记：<无异常 | [具体异常描述，没有就写"无异常"]>
工厂建议：<无 | 如果工厂强但品可疑，建议用户去看工厂其他产品>
综合建议：<一句话，告诉用户现在最该做什么>"""


async def test_one(qwen: QwenAdapter, case: dict) -> dict:
    """跑一个 case 的 LLM 分析。"""

    # 构建数据摘要
    data = f"""商品：{case['title']}
价格：{case['price']} / {case['moq']}{case['unit']}起
销量：{case['sold']}件 | 复购率：{case['repurchase'] if case['repurchase'] else '无数据'} | 好评率：{case['positive_rate'] if case['positive_rate'] else '无数据'} | 想看：{case['wantBuy'] if case['wantBuy'] else '无数据'}
7天退货：{case['return7day']} | 服务：{', '.join(case['service_labels'])}
供应商：{case['supplier_name']} | {case['supplier_location']}
身份：{case['seller_type']}（{case['factory_flags']}）| 认证：{case['cert_type']} | 经营年限：{case['shop_years']}年
规则引擎判定：产品={case['rule_tier']}({case['rule_score']}) 供应商={case['supplier_tier']}({case['supplier_score']}) 综合={case['summary_tier']}
规则判词：{case['rule_verdict']}
供应商判词：{case['supplier_verdict']}"""

    resp = await qwen.chat([
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": data},
    ])

    if resp and "choices" in resp:
        return {"name": case["name"], "output": resp["choices"][0]["message"]["content"]}
    return {"name": case["name"], "output": "❌ API 调用失败"}


async def main():
    qwen = QwenAdapter()
    print("=" * 70)
    print("  规则引擎 vs LLM 判词 — 5 Case 对比测试")
    print("=" * 70)

    for case in CASES:
        print(f"\n{'─'*70}")
        print(f"  📦 {case['name']} | {case['price']} | 销量{case['sold']} | 复购{case['repurchase']} | 关注{case['wantBuy']}")
        print(f"  🏭 {case['seller_type']} | {case['cert_type']} | {case['shop_years']}年")
        print(f"  📏 规则: 产品={case['rule_tier']}({case['rule_score']}) 供应商={case['supplier_tier']} → {case['summary_tier']}")

        result = await test_one(qwen, case)
        print(f"  🤖 LLM:")
        for line in result["output"].strip().split("\n"):
            print(f"     {line.strip()}")

    print(f"\n{'='*70}")
    print("  对比完成。")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
