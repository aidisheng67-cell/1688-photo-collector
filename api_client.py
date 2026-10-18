"""
api_client.py —— 万邦 / onebound 1688 接口适配器（阶段0测试版）

接入说明（据 onebound 官方文档核对，2026-06）：
  - API 地址：https://api-gw.onebound.cn/1688/<接口>/?key=...&secret=...
  - 凭证：key + secret（放 config.yaml，勿进 git / 勿外发）
  - 用到的接口：item_search_img（按图搜款·拍立淘）、item_get（商品详情）、item_review（评论/买家秀）、upload_img（上传图片）
  - 错误表达：HTTP 200 但 success=0 + error/error_code

字段映射均据官方文档；个别（评论图片字段、upload→imgid 衔接）首跑用真实 key 复核，
  程序会把每次原始返回落盘 _pilot_work/last_*.json 便于核对。
"""
import os
import re
import json
import time

import requests


class ThirdPartyApi:
    def __init__(self, cfg, work_dir="./_pilot_work"):
        self.base = cfg["base_url"].rstrip("/")
        self.key = cfg["key"]
        self.secret = cfg.get("secret", "")
        self.qps = cfg.get("qps", 3)
        self.timeout = cfg.get("timeout", 30)
        self.work = work_dir
        os.makedirs(self.work, exist_ok=True)
        self._last = 0.0

    # ---------- 基础设施 ----------
    def _throttle(self):
        wait = 1.0 / self.qps - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.time()

    def _dump(self, name, data):
        try:
            with open(os.path.join(self.work, name), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _redact(self, text):
        from config import redact_text
        return redact_text(text, secrets=(self.key, self.secret))

    def _check(self, data):
        """onebound 约定：error_code 为 '0000'/'0'/'' 且 error 为空/ok 即成功；其余为错误。"""
        if not isinstance(data, dict):
            return data
        code = str(data.get("error_code", "") or "")
        err = str(data.get("error", "") or "")
        ok_codes = {"", "0", "0000"}
        if str(data.get("success", "1")) == "0" or code not in ok_codes \
                or (err and err.lower() != "ok"):
            msg = (f"API错误 {code or data.get('success')}: "
                   f"{data.get('reason') or err or 'unknown'}")
            raise RuntimeError(self._redact(msg))
        return data

    def _get(self, path, params, dump=None):
        self._throttle()
        params = {**params, "key": self.key, "secret": self.secret,
                  "result_type": "json", "lang": "zh-CN"}
        try:
            r = requests.get(f"{self.base}/{path}/", params=params, timeout=self.timeout)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            raise RuntimeError(self._redact(e)) from None
        if dump:
            self._dump(dump, data)
        return self._check(data)

    def _post(self, path, data=None, files=None, dump=None):
        self._throttle()
        params = {"key": self.key, "secret": self.secret, "result_type": "json"}
        try:
            r = requests.post(f"{self.base}/{path}/", params=params,
                              data=data, files=files, timeout=max(self.timeout, 60))
            r.raise_for_status()
            out = r.json()
        except Exception as e:
            raise RuntimeError(self._redact(e)) from None
        if dump:
            self._dump(dump, out)
        return out

    @staticmethod
    def _offer_from_url(url):
        m = re.search(r"offer(?:/|[iI]d=)(\d+)", url or "")
        return m.group(1) if m else ""

    # ---------- 按图搜款（item_search_img · 拍立淘）----------
    def search_by_image(self, imgid, page=1):
        """
        item_search_img：imgid 仅支持【图片 URL】或 upload_img 返回的图片 id。
        本地客户图请先 upload_image() 换 imgid。返回候选列表（统一结构）。
        """
        if not imgid:
            raise ValueError("search_by_image 需要 imgid（图片URL 或 upload_image 返回值）")
        data = self._get("1688/item_search_img", {"imgid": imgid, "page": page},
                         dump="last_search_raw.json")
        return self._parse_candidates(data)

    @staticmethod
    def _strip_avif(url):
        """360buyimg 等用 .avif，拍立淘读不了 → 去掉结尾 .avif 取原图(jpg/png)。"""
        low = (url or "").lower()
        base = low.split("?")[0]
        if base.endswith(".avif"):
            return url[: low.rfind(".avif")]
        return url

    def _download_image(self, url, dst):
        """下图(带 .avif 回退 + UA头 + 重试)，供 upload 兜底用。"""
        ua = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
              "Referer": "https://www.1688.com/"}
        for u in ([url] if url == self._strip_avif(url) else [self._strip_avif(url), url]):
            for attempt in range(3):
                try:
                    r = requests.get(u, headers=ua, timeout=self.timeout)
                    r.raise_for_status()
                    with open(dst, "wb") as f:
                        f.write(r.content)
                    return dst
                except Exception:
                    time.sleep(0.4 * (attempt + 1))
        raise RuntimeError(f"下载图片失败: {url}")

    def search_by_image_robust(self, image_url, page=1):
        """
        A+B 健壮搜款：
          A) 先去掉 .avif 直接用 URL 搜（省 1 次调用）；
          B) 若失败(如 5000 data error / no cache)，下载→转JPEG(upload_img)→按 imgid 搜，兜底。
        返回 (candidates, method)；method ∈ {"url","upload"}。
        """
        try:
            return self.search_by_image(self._strip_avif(image_url), page), "url"
        except Exception as e_a:
            try:
                tmp = os.path.join(self.work, "_qimg.jpg")
                self._download_image(image_url, tmp)
                imgid = self.upload_image(tmp)          # upload_image 内部已转 JPEG 压缩
                return self.search_by_image(imgid, page), "upload"
            except Exception as e_b:
                raise RuntimeError(f"图搜失败 [URL:{e_a}] [上传兜底:{e_b}]")

    @staticmethod
    def _sales_num(it):
        """从常见销量字段解析出数字(接口字段名不固定;取不到则 0),用于按销量排序。"""
        for k in ("sales", "biz30day", "sold", "sold_quantity", "total_sales",
                  "monthSell", "sale_num", "sales_count", "salesCount", "tradeCount"):
            v = it.get(k)
            if v in (None, ""):
                continue
            m = re.search(r"\d[\d,]*", str(v))
            if m:
                try:
                    return int(m.group(0).replace(",", ""))
                except Exception:
                    pass
        return 0

    def _parse_candidates(self, data):
        """映射 items.item[] → 统一结构（num_iid/title/pic_url/detail_url/price/销量，每条仅主图）。"""
        out = []
        for it in (data.get("items") or {}).get("item") or []:
            offer_id = str(it.get("num_iid") or self._offer_from_url(it.get("detail_url", "")))
            # onebound 的 pic_url 可能是逗号拼接的多张图，拆开全用
            pics = [u.strip() for u in str(it.get("pic_url", "") or "").split(",") if u.strip()]
            out.append({
                "offer_id": offer_id,
                "title": it.get("title", ""),
                "main_image": pics[0] if pics else "",
                "image_urls": pics,
                "detail_url": it.get("detail_url", ""),
                "price": it.get("price", ""),
                "sales": it.get("sales") or it.get("biz30day") or "",
                "sales_num": self._sales_num(it),
            })
        return out

    # ---------- 商品详情（item_get）：取详情页全部图 + 卖家信息（评论要用）----------
    def item_get(self, offer_id):
        """返回原始 item dict（含图片字段与卖家信息），并落盘。"""
        data = self._get("1688/item_get", {"num_iid": offer_id}, dump="last_item_get_raw.json")
        return data.get("item") or {}

    @staticmethod
    def _detail_images(item):
        """从 item dict 抽详情图：pic_url + item_imgs[].url + desc_img[]（字段据官方文档）。"""
        imgs = [u.strip() for u in str(item.get("pic_url", "") or "").split(",") if u.strip()]
        for im in (item.get("item_imgs") or []):
            u = im.get("url") if isinstance(im, dict) else im
            if u:
                imgs.append(u)
        imgs += [u for u in (item.get("desc_img") or []) if u]
        return imgs

    @staticmethod
    def _dedup_keep_order(urls):
        seen, out = set(), []
        for u in urls:
            if u and u not in seen:
                seen.add(u); out.append(u)
        return out

    def item_images(self, offer_id):
        """该商品详情图（去重保序）。"""
        return self._dedup_keep_order(self._detail_images(self.item_get(offer_id)))

    def all_images(self, offer_id, with_reviews=True):
        """详情图 + 买家秀图(评论接口)。**始终尝试买家秀**:接口有图就并入、没有/报错就跳过。去重保序。"""
        item = self.item_get(offer_id)
        imgs = self._detail_images(item)
        if with_reviews:
            try:
                imgs += self.review_images(offer_id, nick=item.get("nick"))   # 空则[]，不影响详情图
            except Exception:
                pass
        return self._dedup_keep_order(imgs)

    # ---------- 评论 / 买家秀（item_review）----------
    def review_images(self, offer_id, user_id=None, nick=None, page=1):
        """
        item_review：需 num_iid (+ user_id + nick)。返回买家秀图片 URL 列表。
        ⚠️ 据 onebound 文档响应示例核对（2026-06）：评论项字段为
           content/gmtPublished/levelImg/quantity/raterUserNick/specInfo/starLevel，
           其中 `levelImg` 是【评分/等级徽标小图标】(约60x39)，**不是买家秀实拍图**——故已排除。
           该接口示例里**没有买家秀实拍图字段**，买家秀很可能取不到；
           若个别商品评论确含实拍数组（images/pics/imgs/imageList），这里防御式提取。
           启用前请看落盘 last_review_raw.json 用真实返回再确认。
        """
        params = {"num_iid": offer_id, "page": page}
        if user_id:
            params["user_id"] = user_id
        if nick:
            params["nick"] = nick
        try:
            data = self._get("1688/item_review", params, dump="last_review_raw.json")
        except Exception:
            return []
        out = []
        for rv in (data.get("items") or {}).get("item") or []:
            for key in ("images", "pics", "imgs", "imageList"):   # 不含 levelImg（徽标，非实拍）
                v = rv.get(key)
                if isinstance(v, str):
                    out.append(v)
                elif isinstance(v, list):
                    out += [x.get("url") if isinstance(x, dict) else x for x in v]
        return [u for u in out if u]

    # ---------- 上传本地图片换 imgid（upload_img）----------
    def upload_image(self, local_path, max_side=800, quality=80):
        """
        upload_img：POST imgcode=base64，返回图片 id（实测在 items.item.imgid）。
        作为 imgid 传给 search_by_image。
        ⚠️ 实测：原图过大会报 5000 data error，故先压到 max_side、JPEG quality 再传
           （仅用于搜款检索，不影响后续 pHash/ORB 比对——那用的是原图）。
        """
        import io, base64 as _b64
        from PIL import Image
        im = Image.open(local_path).convert("RGB")
        im.thumbnail((max_side, max_side))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=quality)
        b64 = _b64.b64encode(buf.getvalue()).decode()
        data = self._post("1688/upload_img", data={"imgcode": b64}, dump="last_upload_raw.json")
        self._check(data)
        item = (data.get("items") or {}).get("item") or {}
        imgid = item.get("imgid") or data.get("name") or data.get("url")
        if not imgid:
            raise RuntimeError(f"upload_img 未返回可用 imgid: {data}")
        return str(imgid)
