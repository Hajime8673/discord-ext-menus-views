import discord
from discord.ext import menus

class CollectPageInput(discord.ui.Modal, title='Go To Page'):
    def __init__(self, max_page_value=0):
        super().__init__(timeout=60)
        self.add_item(discord.ui.TextInput(label=f"Page Number (1-{max_page_value})",style=discord.TextStyle.short,max_length=len(str(max_page_value)),min_length=1,row=0,required=True))
        self.value = None

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        value = interaction.data['components'][0]['components'][0]['value']
        self.interaction = interaction
        self.value = value
        self.stop()

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        await interaction.response.send_message('Oops! Something went wrong.', ephemeral=True)
        self.stop()

class ViewMenu(menus.Menu):
    def __init__(self, *, auto_defer=True, **kwargs):
        super().__init__(**kwargs)
        self.auto_defer = auto_defer
        self.view = None
        self.__tasks = []

    def build_view(self):
        if not self.should_add_reactions():
            return None

        emoji_label = {4: 'Go To Page', 5: 'Close Paginator'}
        def make_callback(button):
            async def callback(interaction):
                if interaction.user.id not in {self.bot.owner_id, self._author_id, *self.bot.owner_ids, *self._allowed_user_ids}:
                    return await interaction.response.send_message('You are not allowed to use this button.', ephemeral=True)
                if self.auto_defer:
                    await interaction.response.defer()
                try:
                    if button.lock:
                        async with self._lock:
                            if self._running:
                                await button(self, interaction)
                    else:
                        await button(self, interaction)
                except Exception as exc:
                    await self.on_menu_button_error(exc)

            return callback
        
        def make_go_to_page_callback(button):
            async def callback(interaction: discord.Interaction):
                if interaction.user.id not in {self.bot.owner_id, self._author_id, *self.bot.owner_ids, *self._allowed_user_ids}:
                    return
                
                modal = CollectPageInput(self.max_page_value)
                await interaction.response.send_modal(modal)
                await modal.wait()
                if modal.value is None:
                    return
                try:
                    value = int(modal.value)
                except:
                    await modal.interaction.followup.send('Input value could not be converted to a page number.', ephemeral=True)
                    return
                if value < 1:
                    value = 1
                if value > self.max_page_value:
                    value = self.max_page_value
                try:
                    if button.lock:
                        async with self._lock:
                            if self._running:
                                await button(self, interaction, value)
                    else:
                        await button(self, interaction, value)
                except Exception as exc:
                    print(exc)
                    await self.on_menu_button_error(exc)

            return callback

        view = discord.ui.View(timeout=self.timeout)
        for i, (emoji, button) in enumerate(self.buttons.items()):
            item = discord.ui.Button(style=discord.ButtonStyle.blurple if i == 4 else (discord.ButtonStyle.gray if i != 5 else discord.ButtonStyle.red), emoji=emoji, row=i // 4, label=emoji_label.get(i, None))
            if i != 4:
                item.callback = make_callback(button)
            else:
                item.callback = make_go_to_page_callback(button)
            view.add_item(item)

        self.view = view
        return view

    def add_button(self, button, *, react=False):
        super().add_button(button)

        if react:
            if self.__tasks:
                async def wrapped():
                    self.buttons[button.emoji] = button
                    try:
                        await self.message.edit(view=self.build_view())
                    except discord.HTTPException:
                        raise
                return wrapped()

            async def dummy():
                raise menus.MenuError("Menu has not been started yet")
            return dummy()

    def remove_button(self, emoji, *, react=False):
        super().remove_button(emoji)

        if react:
            if self.__tasks:
                async def wrapped():
                    self.buttons.pop(emoji, None)
                    try:
                        await self.message.edit(view=self.build_view())
                    except discord.HTTPException:
                        raise
                return wrapped()

            async def dummy():
                raise menus.MenuError("Menu has not been started yet")
            return dummy()

    def clear_buttons(self, *, react=False):
        super().clear_buttons()

        if react:
            if self.__tasks:
                async def wrapped():
                    try:
                        await self.message.edit(view=None)
                    except discord.HTTPException:
                        raise
                return wrapped()

            async def dummy():
                raise menus.MenuError("Menu has not been started yet")
            return dummy()

    async def _internal_loop(self):
        self.__timed_out = False
        try:
            self.__timed_out = await self.view.wait()
        except Exception:
            pass
        finally:
            self._event.set()

            try:
                await self.finalize(self.__timed_out)
            except Exception:
                pass
            finally:
                self.__timed_out = False

            if self.bot.is_closed():
                return

            try:
                if self.delete_message_after:
                    return await self.message.delete()

                if self.clear_reactions_after:
                    return await self.message.edit(view=None)
            except Exception:
                pass

    async def start(self, ctx, *, channel=None, wait=False, allowed_user_ids=None):
        try:
            del self.buttons
        except AttributeError:
            pass

        if allowed_user_ids is None:
            self._allowed_user_ids = set()
        else:
            self._allowed_user_ids = set(allowed_user_ids)

        self.bot = bot = ctx.bot
        self.ctx = ctx
        self._author_id = ctx.author.id
        channel = channel or ctx.channel
        is_guild = hasattr(channel, "guild") and channel.guild is not None
        me = channel.guild.me if is_guild else ctx.bot.user
        permissions = channel.permissions_for(me)
        self._verify_permissions(ctx, channel, permissions)
        self._event.clear()
        msg = self.message
        if msg is None:
            self.message = msg = await self.send_initial_message(ctx, channel)

        if self.should_add_reactions():
            for task in self.__tasks:
                task.cancel()
            self.__tasks.clear()

            self._running = True
            self.__tasks.append(bot.loop.create_task(self._internal_loop()))

            if wait:
                await self._event.wait()

    def send_with_view(self, messageable, *args, **kwargs):
        return messageable.send(*args, **kwargs, view=self.build_view())

    def stop(self):
        self._running = False
        for task in self.__tasks:
            task.cancel()
        self.__tasks.clear()


class ViewMenuPages(menus.MenuPages, ViewMenu):
    def __init__(self, source, **kwargs):
        self._source = source
        self.max_page_value = source.get_max_pages()
        self.current_page = 0
        super().__init__(source, **kwargs)

    async def send_initial_message(self, ctx, channel):
        page = await self._source.get_page(0)
        kwargs = await self._get_kwargs_from_page(page)
        return await self.send_with_view(channel, **kwargs)
