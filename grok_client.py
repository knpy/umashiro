"""Grok (xAI) APIを使ってXの競馬予想ポストを検索・集約する"""

import json
import re
from openai import OpenAI


class GrokClient:
    """xAI APIクライアント - Xの競馬予想を収集する"""

    def __init__(self, api_key: str, model: str = "grok-3"):
        self.client = OpenAI(
            api_key=api_key,
            base_url="https://api.x.ai/v1",
        )
        self.model = model

    def search_predictions(self, venue: str, date: str, race_number: int = 0) -> dict:
        """
        Xの競馬予想ポストを検索し、集約結果を返す。

        Args:
            venue: 会場名 (例: "中山")
            date: 日付 (YYYYMMDD)
            race_number: レース番号 (0=全レース)

        Returns:
            dict with keys: consensus, top_picks, notable_opinions, raw_summary
        """
        # 検索クエリの組み立て
        date_str = f"{date[:4]}年{int(date[4:6])}月{int(date[6:8])}日"
        race_str = f"{race_number}R" if race_number else ""

        prompt = f"""Xで今日（{date_str}）の{venue}競馬{race_str}の予想に関するポストを検索して分析してください。

以下を調べてください:
1. 有力な競馬予想アカウントの予想（◎○▲△の印）
2. 多くの人が推している馬（コンセンサス）
3. 穴馬として注目されている馬
4. 馬場状態や展開に関する情報

以下のJSON形式で結果をまとめてください:

```json
{{
  "consensus_picks": [
    {{
      "horse_name": "馬名",
      "horse_number": "馬番（わかれば）",
      "support_level": "多数/複数/少数",
      "typical_mark": "◎ or ○ or ▲ etc"
    }}
  ],
  "notable_opinions": [
    {{
      "source": "アカウント名や予想家名（わかれば）",
      "opinion": "予想内容の要約",
      "reasoning": "理由"
    }}
  ],
  "track_info": {{
    "condition": "馬場状態に関する情報",
    "bias": "馬場バイアスに関する情報（内外差、前後差など）",
    "weather": "天気に関する情報"
  }},
  "dark_horses": [
    {{
      "horse_name": "穴馬名",
      "reason": "注目理由"
    }}
  ],
  "summary": "全体的な予想の傾向まとめ（200字程度）"
}}
```

ポストが見つからない場合や情報が不十分な場合は、わかる範囲でまとめ、不明な項目はnullとしてください。"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "あなたは日本競馬の予想情報を収集・分析するアシスタントです。"
                            "Xのポストから競馬予想の情報を正確に抽出してください。"
                            "情報がない場合は推測せず、不明と答えてください。"
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                search_mode="auto",
            )

            text = response.choices[0].message.content

            # JSONを抽出
            json_match = text
            if "```json" in text:
                json_match = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                json_match = text.split("```")[1].split("```")[0]

            return json.loads(json_match.strip())

        except json.JSONDecodeError:
            return {"raw_summary": text, "error": "JSON parse failed"}
        except Exception:
            return {"error": "Failed to fetch predictions", "raw_summary": ""}

    def get_expert_predictions(self, venue: str, race_name: str, race_number: int) -> dict:
        """特定レースの専門家予想を取得"""
        prompt = f"""Xで「{venue}{race_number}R {race_name}」の予想を検索してください。

特に以下を重視して探してください:
- フォロワー数が多い、または的中実績のある予想アカウント
- 具体的な印（◎○▲△×）や買い目を出しているポスト
- データに基づいた分析をしているポスト

結果を以下の形式でまとめてください:

```json
{{
  "expert_picks": [
    {{
      "source": "予想家/アカウント名",
      "honmei": "◎本命の馬名",
      "taikou": "○対抗の馬名",
      "tanana": "▲単穴の馬名",
      "renka": ["△連下の馬名リスト"],
      "recommended_bet": "おすすめ馬券（あれば）",
      "reasoning": "予想理由の要約"
    }}
  ],
  "aggregated": {{
    "most_popular_honmei": "最も◎が多かった馬名",
    "most_popular_taikou": "最も○が多かった馬名",
    "agreement_level": "予想家間の一致度（高/中/低）"
  }}
}}
```"""

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "日本競馬の予想情報アナリストとして、Xのポストから予想を正確に収集してください。",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                search_mode="auto",
            )

            text = response.choices[0].message.content
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]

            return json.loads(text.strip())

        except json.JSONDecodeError:
            return {"raw_summary": response.choices[0].message.content}
        except Exception as e:
            return {"error": str(e)}


def grok_result_to_text(result: dict) -> str:
    """Grokの結果をテキスト形式に変換（Claude分析用）"""
    lines = ["## X(Twitter)の予想情報\n"]

    if "error" in result and not result.get("consensus_picks"):
        lines.append(f"※ X予想の取得に問題がありました: {result.get('error', '不明')}")
        if result.get("raw_summary"):
            lines.append(result["raw_summary"])
        return "\n".join(lines)

    # コンセンサス
    consensus = result.get("consensus_picks", [])
    if consensus:
        lines.append("### コンセンサス（多数派の予想）")
        for c in consensus:
            lines.append(
                f"- {c.get('horse_name', '?')} "
                f"(馬番{c.get('horse_number', '?')}) "
                f"支持:{c.get('support_level', '?')} "
                f"印:{c.get('typical_mark', '?')}"
            )
        lines.append("")

    # 注目意見
    opinions = result.get("notable_opinions", [])
    if opinions:
        lines.append("### 注目意見")
        for o in opinions:
            lines.append(f"- [{o.get('source', '匿名')}] {o.get('opinion', '')} ({o.get('reasoning', '')})")
        lines.append("")

    # 馬場情報
    track = result.get("track_info", {})
    if track and any(track.values()):
        lines.append("### 馬場・天気情報")
        if track.get("condition"):
            lines.append(f"- 馬場: {track['condition']}")
        if track.get("bias"):
            lines.append(f"- バイアス: {track['bias']}")
        if track.get("weather"):
            lines.append(f"- 天気: {track['weather']}")
        lines.append("")

    # 穴馬
    dark = result.get("dark_horses", [])
    if dark:
        lines.append("### 穴馬候補")
        for d in dark:
            lines.append(f"- {d.get('horse_name', '?')}: {d.get('reason', '')}")
        lines.append("")

    # サマリー
    summary = result.get("summary")
    if summary:
        lines.append(f"### まとめ\n{summary}")

    return "\n".join(lines)
