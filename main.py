import random
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star
from astrbot.api import AstrBotConfig, logger
from astrbot.api.message_components import Plain, Image


class NicknameChangeMonitor(Star):
    """监听群名片修改，随机发送可爱播报（支持群白名单）"""

    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config

    @staticmethod
    def _normalize_whitelist(whitelist) -> list:
        """
        将配置中的白名单安全地归一化为字符串列表。
        兼容用户误填单个整数 / 字符串 / None 的情况，避免 TypeError。
        """
        if whitelist is None:
            return []
        if isinstance(whitelist, (str, int)):
            return [str(whitelist)]
        if isinstance(whitelist, (list, tuple, set)):
            return [str(g) for g in whitelist]
        logger.warning(
            f"group_whitelist 配置类型异常({type(whitelist).__name__})，已忽略白名单设置"
        )
        return []

    async def get_qq_nickname(self, event: AstrMessageEvent, group_id, qq: str) -> str:
        """
        获取 QQ 昵称。
        当群昵称为空时，群内实际显示的是 QQ 昵称。
        """
        if not qq:
            return ""

        try:
            raw = event.message_obj.raw_message
            if isinstance(raw, dict):
                sender = raw.get("sender")
                sender = sender if isinstance(sender, dict) else {}
                nickname = (
                    raw.get("nickname")
                    or raw.get("user_name")
                    or sender.get("nickname", "")
                )
                if nickname:
                    return str(nickname)
        except (AttributeError, KeyError, TypeError) as e:
            logger.debug(f"从 raw_message 解析昵称失败: {e}")

        try:
            client = event.bot
            info = await client.api.call_action(
                "get_group_member_info",
                group_id=int(group_id),
                user_id=int(qq),
                no_cache=True,
            )
            nickname = info.get("nickname", "") if isinstance(info, dict) else ""
            if nickname:
                return str(nickname)
        except (AttributeError, NotImplementedError):
            logger.debug("当前适配器不支持 get_group_member_info，跳过昵称查询")
        except Exception as e:
            logger.warning(
                f"调用 get_group_member_info 获取昵称失败: "
                f"group={group_id}, user={qq}, error={e}"
            )

        logger.warning(f"获取 QQ 昵称失败，将使用 QQ 号兜底: group={group_id}, user={qq}")
        return qq

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        if not self.config.get("enabled", True):
            return

        raw = event.message_obj.raw_message
        if not isinstance(raw, dict):
            return

        if raw.get("notice_type") != "group_card":
            return

        old_name = raw.get("card_old", "")
        new_name = raw.get("card_new", "")
        qq = str(raw.get("user_id", ""))
        group_id = raw.get("group_id")

        whitelist = self._normalize_whitelist(self.config.get("group_whitelist", []))
        if whitelist and str(group_id) not in whitelist:
            logger.debug(f"群 {group_id} 不在白名单中，跳过播报")
            return

        qq_nickname = None
        if not old_name or not new_name:
            qq_nickname = await self.get_qq_nickname(event, group_id, qq)

        if not old_name:
            old_name = qq_nickname
        if not new_name:
            new_name = qq_nickname

        logger.info(f"检测到群名片变更: {old_name}({qq}) -> {new_name}")

        texts = self.config.get("custom_texts", [])
        if isinstance(texts, str):
            texts = [texts]
        if not texts:
            texts = [
                "✨ 叮咚！{old} 摇身一变成了 {new}！是不是偷偷转职啦？(≧▽≦)",
                "🎈 哇～ {old} 悄悄换了个新名片：{new} ！快看快看～",
                "🍭 捕捉到一只改名怪！{old} → {new} 可爱度+10 ✨",
                "🌸 叮！{old} 决定重新做人……啊不对，重新叫 {new} 啦！",
                "❄ {old} 把名字藏起来了，现在请叫我 {new} ～",
                "📛 旧名回收站：{old} 已清理。🎉 新名上线：{new}！",
                "🔔 群聊震动！{old} 换上了闪亮新马甲：{new} 💎",
            ]

        chosen_text = random.choice(texts)
        text = chosen_text.format(old=old_name, new=new_name, qq=qq)

        chain = [Plain(text)]

        if qq:
            try:
                avatar_url = f"https://q1.qlogo.cn/g?b=qq&nk={qq}&s=640"
                chain.append(Image.fromURL(avatar_url))
            except Exception as e:
                logger.debug(f"头像构建失败，将仅发送文本: {e}")

        try:
            yield event.chain_result(chain)
        except Exception as e:
            logger.error(f"发送播报失败: {e}")

        event.stop_event()

    async def terminate(self):
        pass
