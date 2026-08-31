from flask import Flask, render_template, jsonify, request
import yfinance as yf

app = Flask(__name__)


def analyze_stock(symbol: str) -> dict:
    """주식 기본 데이터 수집 및 간단 AI 분석"""
    ticker = yf.Ticker(symbol)
    info = ticker.info
    hist = ticker.history(period="3mo")

    if hist.empty:
        return {"error": f"'{symbol}' 종목을 찾을 수 없습니다."}

    current = hist["Close"].iloc[-1]
    prev = hist["Close"].iloc[-2] if len(hist) > 1 else current
    change_pct = ((current - prev) / prev) * 100

    ma20 = hist["Close"].rolling(20).mean().iloc[-1]
    ma60 = hist["Close"].rolling(60).mean().iloc[-1] if len(hist) >= 60 else None

    signals = []
    if current > ma20:
        signals.append("단기 상승 추세 (20일 이동평균선 상회)")
    else:
        signals.append("단기 하락 추세 (20일 이동평균선 하회)")

    if ma60 and current > ma60:
        signals.append("중기 상승 추세 (60일 이동평균선 상회)")
    elif ma60:
        signals.append("중기 하락 추세 (60일 이동평균선 하회)")

    if change_pct > 2:
        signals.append("전일 대비 강한 상승")
    elif change_pct < -2:
        signals.append("전일 대비 강한 하락")

    score = 50
    if current > ma20:
        score += 15
    if ma60 and current > ma60:
        score += 15
    if change_pct > 0:
        score += 10
    if change_pct < -3:
        score -= 10

    score = max(0, min(100, score))

    if score >= 70:
        recommendation = "매수 관심"
        sentiment = "positive"
    elif score >= 40:
        recommendation = "관망"
        sentiment = "neutral"
    else:
        recommendation = "주의"
        sentiment = "negative"

    return {
        "symbol": symbol.upper(),
        "name": info.get("shortName") or info.get("longName") or symbol.upper(),
        "price": round(current, 2),
        "change_pct": round(change_pct, 2),
        "market_cap": info.get("marketCap"),
        "pe_ratio": info.get("trailingPE"),
        "signals": signals,
        "score": score,
        "recommendation": recommendation,
        "sentiment": sentiment,
        "history": [
            {"date": d.strftime("%Y-%m-%d"), "close": round(v, 2)}
            for d, v in hist["Close"].items()
        ],
    }


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/api/analyze")
def api_analyze():
    symbol = request.args.get("symbol", "").strip().upper()
    if not symbol:
        return jsonify({"error": "종목 코드를 입력해 주세요."}), 400

    try:
        result = analyze_stock(symbol)
        if "error" in result:
            return jsonify(result), 404
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": f"분석 중 오류: {str(e)}"}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
