# expert: app_install
# description: Ставит приложение по рецепту (формат Pinokio, БЕЗ LLM): клонирует репо → резолвит install.js через Node (под GPU/платформу) → исполняет shell-шаги в изолир. venv → пишет реестр плагина + старт. Node нужен (разовый brew). Возвращает {status, plugin_id, steps}.
def app_install(repo="", app_id="", branch="main"):
    import os, json, subprocess, sys, tempfile, shutil, base64, re
    def err(m): return json.dumps({"status":"error","message":m,"app_id":app_id}, ensure_ascii=False)
    repo=(repo or "").strip()
    if not app_id:
        app_id = re.sub(r"[^a-z0-9]+","_", (repo.rstrip("/").split("/")[-1] or "app").lower())
    root = os.path.expanduser("~/extella-apps/"+app_id)
    try:
        from extella_expert_bridge import path_or_error
    except Exception:
        return err("Системный runtime Extella не установлен. Запустите Repair Extella Client.")
    node, node_state = path_or_error("node", repair=True)
    if not node: return err(node_state.get("message") or "Node.js недоступен")
    # 1. клон / локальная папка
    if repo.startswith("http") or repo.startswith("git@"):
        if os.path.isdir(os.path.join(root,".git")):
            subprocess.run(["git","-C",root,"pull","--depth","1"],capture_output=True,text=True,timeout=180)
        else:
            os.makedirs(os.path.dirname(root),exist_ok=True); shutil.rmtree(root,ignore_errors=True)
            r=subprocess.run(["git","clone","--depth","1","-b",branch,repo,root],capture_output=True,text=True,timeout=300)
            if r.returncode!=0:
                r=subprocess.run(["git","clone","--depth","1",repo,root],capture_output=True,text=True,timeout=300)
                if r.returncode!=0: return err("клон не удался: "+(r.stderr or "")[-120:])
    elif os.path.isdir(os.path.expanduser(repo)):
        root=os.path.expanduser(repo)
    else:
        return err("repo не URL и не локальная папка")
    if not (os.path.exists(os.path.join(root,"install.js")) or os.path.exists(os.path.join(root,"pinokio.js"))):
        return err("в репо нет install.js/pinokio.js — не Pinokio-рецепт")
    # 2. резолвер (встроенный) → плоские шаги
    resolve_js=os.path.join(root,".extella_resolve.js")
    open(resolve_js,"wb").write(base64.b64decode("""Ly8g0KDQtdC30L7Qu9Cy0LXRgCBQaW5va2lvLdGA0LXRhtC10L/RgtC+0LIg4oaSINC/0LvQvtGB0LrQuNC1IHNoZWxsLnJ1biDRiNCw0LPQuCArINC/0L7RgNGCICjQtNC10YLQtdGA0LzQuNC90LjRgNC+0LLQsNC90L3Qviwg0YHQstC+0Lkg0LzQuNC90Lgta2VybmVsKS4KLy8gbm9kZSByZWNpcGVfcmVzb2x2ZS5qcyA8YXBwX2Rpcj4gPGVudHJ5LmpzPiBbZ3B1XSBbcGxhdGZvcm1dIFtmaXhlZF9wb3J0XQpjb25zdCBwYXRoID0gcmVxdWlyZSgncGF0aCcpOwpjb25zdCBvcyA9IHJlcXVpcmUoJ29zJyk7CmNvbnN0IG5ldCA9IHJlcXVpcmUoJ25ldCcpOwpjb25zdCBjcCA9IHJlcXVpcmUoJ2NoaWxkX3Byb2Nlc3MnKTsKY29uc3QgZnMgPSByZXF1aXJlKCdmcycpOwpjb25zdCB2bSA9IHJlcXVpcmUoJ3ZtJyk7CgovLyDilIDilIAg0J/QldCh0J7Qp9Cd0JjQptCQIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAovLyDQoNC10YbQtdC/0YLRiyDigJQg0YfRg9C20L7QuSBKUyDQuNC3INGB0LrQu9C+0L3QuNGA0L7QstCw0L3QvdC+0LPQviDRgNC10L/Qvi4g0J3QldCb0KzQl9CvINC40YHQv9C+0LvQvdGP0YLRjCDQtdCz0L4g0YEg0L/QvtC70L3Ri9C80LgKLy8g0L/RgNCw0LLQsNC80LggTm9kZSAoZnMvY2hpbGRfcHJvY2Vzcy/RgdC10YLRjC9wcm9jZXNzLmVudi3RgdC10LrRgNC10YLRiykuINCT0YDRg9C30LjQvCDRgNC10YbQtdC/0YIg0LIKLy8gdm0t0LrQvtC90YLQtdC60YHRgjog0LTQvtGB0YLRg9C/0L3RiyDRgtC+0LvRjNC60L4gbW9kdWxlL2V4cG9ydHMsINCx0LXQt9Cy0YDQtdC00L3Ri9C1IHBhdGh8b3MsINC4IHJlcXVpcmUKLy8g0YHQvtGB0LXQtNC90LjRhSAuanMg0YDQtdGG0LXQv9GC0L7QsiAo0YLQvtC20LUg0LIg0L/QtdGB0L7Rh9C90LjRhtC1KS4g0JLRgdGRINC+0YHRgtCw0LvRjNC90L7QtSAoZnMsIGNoaWxkX3Byb2Nlc3MsCi8vIG5ldCwgaHR0cOKApikg4oCUINC30LDQsdC70L7QutC40YDQvtCy0LDQvdC+LiDQntC/0LDRgdC90YvQtSDQvtC/0LXRgNCw0YbQuNC4ICh3aGljaC9leGlzdHMpINC00LXQu9Cw0LXRgiDQndCQ0KgKLy8ga2VybmVsLCDQsCDQvdC1INGA0LXRhtC10L/Rgi4KY29uc3QgU0FGRV9NT0RVTEVTID0geyBwYXRoOiBwYXRoLCBvczogeyBwbGF0Zm9ybTooKT0+cHJvY2Vzcy5wbGF0Zm9ybSwgYXJjaDooKT0+b3MuYXJjaCgpLCBob21lZGlyOigpPT5vcy5ob21lZGlyKCksIGNwdXM6KCk9Pm9zLmNwdXMoKSwgdG90YWxtZW06KCk9Pm9zLnRvdGFsbWVtKCksIHR5cGU6KCk9Pm9zLnR5cGUoKSB9IH07CmZ1bmN0aW9uIG1ha2VTYW5kYm94UmVxdWlyZShiYXNlRGlyLCBrZXJuZWwsIHNlZW4pewogIHJldHVybiBmdW5jdGlvbiBzYW5kYm94UmVxdWlyZShzcGVjKXsKICAgIGlmKFNBRkVfTU9EVUxFU1tzcGVjXSkgcmV0dXJuIFNBRkVfTU9EVUxFU1tzcGVjXTsKICAgIGlmKC9eXC5cLj9cLy8udGVzdChzcGVjKSl7ICAgICAgICAgICAgICAgICAgICAgICAgIC8vINGB0L7RgdC10LTQvdC40Lkg0YTQsNC50Lst0YDQtdGG0LXQv9GCCiAgICAgIGxldCBmID0gcGF0aC5yZXNvbHZlKGJhc2VEaXIsIHNwZWMpOwogICAgICBpZighL1wuanMob24pPyQvLnRlc3QoZikgJiYgZnMuZXhpc3RzU3luYyhmKycuanMnKSkgZj1mKycuanMnOwogICAgICBpZihmLmVuZHNXaXRoKCcuanNvbicpKXsgdHJ5eyByZXR1cm4gSlNPTi5wYXJzZShmcy5yZWFkRmlsZVN5bmMoZiwndXRmOCcpKTsgfWNhdGNoKGUpeyByZXR1cm4ge307IH0gfQogICAgICBpZighZi5zdGFydHNXaXRoKGtlcm5lbC5fcm9vdCkpIHRocm93IG5ldyBFcnJvcignc2FuZGJveDog0L/Rg9GC0Ywg0LLQvdC1INC/0YDQuNC70L7QttC10L3QuNGPOiAnK3NwZWMpOwogICAgICBpZihzZWVuLmhhcyhmKSkgcmV0dXJuIHt9OyAgICAgICAgICAgICAgICAgICAgICAgIC8vINC30LDRidC40YLQsCDQvtGCINGG0LjQutC70L7QsgogICAgICBzZWVuLmFkZChmKTsKICAgICAgcmV0dXJuIHJ1bkluU2FuZGJveChmLCBrZXJuZWwsIHNlZW4pOwogICAgfQogICAgdGhyb3cgbmV3IEVycm9yKCdzYW5kYm94OiDQvNC+0LTRg9C70Ywg0LfQsNC/0YDQtdGJ0ZHQvTogJytzcGVjKTsgLy8gZnMvY2hpbGRfcHJvY2Vzcy9uZXQvaHR0cC/igKYKICB9Owp9CmZ1bmN0aW9uIHJ1bkluU2FuZGJveChmaWxlLCBrZXJuZWwsIHNlZW4pewogIGNvbnN0IGNvZGUgPSBmcy5yZWFkRmlsZVN5bmMoZmlsZSwgJ3V0ZjgnKTsKICBjb25zdCBzYW5kYm94ID0gewogICAgbW9kdWxlOntleHBvcnRzOnt9fSwgZXhwb3J0czp7fSwKICAgIHJlcXVpcmU6IG1ha2VTYW5kYm94UmVxdWlyZShwYXRoLmRpcm5hbWUoZmlsZSksIGtlcm5lbCwgc2VlbiksCiAgICBjb25zb2xlOiB7IGxvZzooKT0+e30sIGVycm9yOigpPT57fSwgd2FybjooKT0+e30gfSwKICAgIC8vINCx0LXQt9Cy0YDQtdC00L3Ri9C5IHByb2Nlc3M6INGC0L7Qu9GM0LrQviDQv9C70LDRgtGE0L7RgNC80LAv0LDRgNGFLCDQkdCV0JcgZW52L2V4aXQvY3dkLdC30LDQv9C40YHQuC9hcmd2CiAgICBwcm9jZXNzOiB7IHBsYXRmb3JtOnByb2Nlc3MucGxhdGZvcm0sIGFyY2g6b3MuYXJjaCgpLCBlbnY6e30sIHZlcnNpb246cHJvY2Vzcy52ZXJzaW9uIH0sCiAgICBCdWZmZXI6IEJ1ZmZlciwgc2V0VGltZW91dDooKT0+e30sIGNsZWFyVGltZW91dDooKT0+e30sIF9fZGlybmFtZTpwYXRoLmRpcm5hbWUoZmlsZSksIF9fZmlsZW5hbWU6ZmlsZSwKICB9OwogIHNhbmRib3guZ2xvYmFsID0gc2FuZGJveDsgc2FuZGJveC5nbG9iYWxUaGlzID0gc2FuZGJveDsKICB2bS5jcmVhdGVDb250ZXh0KHNhbmRib3gpOwogIHZtLnJ1bkluQ29udGV4dChjb2RlLCBzYW5kYm94LCB7IGZpbGVuYW1lOmZpbGUsIHRpbWVvdXQ6NTAwMCB9KTsgICAvLyA10YEg0L/QvtGC0L7Qu9C+0Log0L3QsCDQt9Cw0LPRgNGD0LfQutGDCiAgY29uc3QgbWUgPSBzYW5kYm94Lm1vZHVsZS5leHBvcnRzOyAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAvLyDRhNGD0L3QutGG0LjRjyDQmNCb0Jgg0L3QtdC/0YPRgdGC0L7QuSDQvtCx0YrQtdC60YIg4oaSINGN0YLQviDQuCDQtdGB0YLRjCDRgNC10YbQtdC/0YIKICBpZih0eXBlb2YgbWU9PT0nZnVuY3Rpb24nIHx8IChtZSAmJiBPYmplY3Qua2V5cyhtZSkubGVuZ3RoKSkgcmV0dXJuIG1lOwogIHJldHVybiBzYW5kYm94LmV4cG9ydHM7Cn0KCmZ1bmN0aW9uIGRldGVjdEdwdSgpeyBpZihwcm9jZXNzLnBsYXRmb3JtPT09J2RhcndpbicpIHJldHVybiBvcy5hcmNoKCk9PT0nYXJtNjQnPydhcHBsZSc6J2NwdSc7CiAgdHJ5eyBjcC5leGVjU3luYygnbnZpZGlhLXNtaScse3N0ZGlvOidpZ25vcmUnfSk7IHJldHVybiAnbnZpZGlhJzsgfWNhdGNoKGUpe30gcmV0dXJuICdjcHUnOyB9CmZ1bmN0aW9uIGZyZWVQb3J0U3luYyhwcmVmKXsKICBpZihwcmVmKSByZXR1cm4gcHJlZjsKICB0cnl7IGNvbnN0IHM9bmV0LmNyZWF0ZVNlcnZlcigpOyByZXR1cm4gbmV3IFByb21pc2UocmVzPT57IHMubGlzdGVuKDAsKCk9Pntjb25zdCBwPXMuYWRkcmVzcygpLnBvcnQ7IHMuY2xvc2UoKCk9PnJlcyhwKSk7fSk7IH0pOyB9CiAgY2F0Y2goZSl7IHJldHVybiA3ODYwOyB9Cn0KCi8vINCc0LjQvdC4LWtlcm5lbCAo0YLQviwg0YfRgtC+INGA0LXRhtC10L/RgtGLINC20LTRg9GCINC+0YIgUGlub2tpbykKZnVuY3Rpb24gbWFrZUtlcm5lbChyb290LCBmb3JjZWRQb3J0KXsKICBjb25zdCBncHUgPSBwcm9jZXNzLmVudi5SRUNfR1BVIHx8IGRldGVjdEdwdSgpOwogIGNvbnN0IHBsYXRmb3JtID0gcHJvY2Vzcy5lbnYuUkVDX1BMQVRGT1JNIHx8IHByb2Nlc3MucGxhdGZvcm07CiAgbGV0IF9wb3J0ID0gZm9yY2VkUG9ydCB8fCBudWxsOwogIHJldHVybiB7CiAgICBfcm9vdDogcGF0aC5yZXNvbHZlKHJvb3QpLAogICAgZ3B1LCBwbGF0Zm9ybSwgYXJjaDogb3MuYXJjaCgpLCBob21lZGlyOiBvcy5ob21lZGlyKCksCiAgICBwb3J0OiBhc3luYyAoKSA9PiB7IGlmKCFfcG9ydCl7IF9wb3J0ID0gYXdhaXQgZnJlZVBvcnRTeW5jKG51bGwpOyB9IHJldHVybiBfcG9ydDsgfSwKICAgIHBhdGg6ICguLi5hKSA9PiBwYXRoLnJlc29sdmUocm9vdCwgLi4uYSksCiAgICB3aGljaDogKGMpID0+IHsgdHJ5eyByZXR1cm4gY3AuZXhlY1N5bmMoKHByb2Nlc3MucGxhdGZvcm09PT0nd2luMzInPyd3aGVyZSAnOid3aGljaCAnKStjKS50b1N0cmluZygpLnRyaW0oKS5zcGxpdCgnXG4nKVswXTsgfWNhdGNoKGUpeyByZXR1cm4gbnVsbDsgfSB9LAogICAgZXhpc3RzOiAocCkgPT4gcmVxdWlyZSgnZnMnKS5leGlzdHNTeW5jKHBhdGgucmVzb2x2ZShyb290LHApKSwKICAgIGFwaToge30sIG1lbW9yeToge30sIGJpbjogeyBwYXRoOiAoKT0+cGF0aC5qb2luKG9zLmhvbWVkaXIoKSwncGlub2tpbycsJ2JpbicpIH0sCiAgICBfZ2V0UG9ydDogKCkgPT4gX3BvcnQsCiAgfTsKfQoKZnVuY3Rpb24gdG1wbCh2YWwsYyl7IGlmKHR5cGVvZiB2YWwhPT0nc3RyaW5nJ3x8IXZhbC5pbmNsdWRlcygne3snKSkgcmV0dXJuIHZhbDsKICByZXR1cm4gdmFsLnJlcGxhY2UoL1x7XHsoW1xzXFNdKj8pXH1cfS9nLChfLGUpPT57IHRyeXsgY29uc3QgZj1uZXcgRnVuY3Rpb24oJ2dwdScsJ3BsYXRmb3JtJywnYXJjaCcsJ2FyZ3MnLCdpbnB1dCcsJ2N3ZCcsJ3BvcnQnLCdleGlzdHMnLCd3aGljaCcsJ2tlcm5lbCcsJ3BhdGgnLCdyZXR1cm4gKCcrZSsnKScpOwogICAgY29uc3Qgcj1mKGMuZ3B1LGMucGxhdGZvcm0sYy5hcmNoLGMuYXJnc3x8e30sYy5pbnB1dHx8e30sYy5jd2QsYy5wb3J0LGMuZXhpc3RzLGMud2hpY2gsYy5rZXJuZWwscGF0aCk7IHJldHVybiAocj09bnVsbCk/Jyc6U3RyaW5nKHIpO31jYXRjaCh4KXtyZXR1cm4gJyc7fSB9KTsgfQpmdW5jdGlvbiB0bXBsRGVlcChvLGMpeyBpZihBcnJheS5pc0FycmF5KG8pKSByZXR1cm4gby5tYXAoeD0+dG1wbERlZXAoeCxjKSkuZmlsdGVyKHg9PnghPT0nJyYmeCE9PW51bGwpOwogIGlmKG8mJnR5cGVvZiBvPT09J29iamVjdCcpe2NvbnN0IHI9e307Zm9yKGNvbnN0IGsgaW4gbylyW2tdPXRtcGxEZWVwKG9ba10sYyk7cmV0dXJuIHI7fSByZXR1cm4gdG1wbChvLGMpOyB9CmZ1bmN0aW9uIGV2YWxXaGVuKHdoZW4sYyl7IGlmKCF3aGVuKSByZXR1cm4gdHJ1ZTsKICAvLyBQaW5va2lvLdGD0YHQu9C+0LLQuNGPINC40YHQv9C+0LvRjNC30YPRjtGCIGV4aXN0cygpL3doaWNoKCkg0Y/QtNGA0LAg4oCUINCx0LXQtyDQvdC40YUgUmVmZXJlbmNlRXJyb3IKICAvLyDRgtC40YXQviDQv9GA0LXQstGA0LDRidCw0LvRgdGPINCyIGZhbHNlINC4INGI0LDQs9C4ICjQvdCw0L/RgNC40LzQtdGAIGdpdCBjbG9uZSBzZWFyeG5nIGFwcCkg0JLQq9Cf0JDQlNCQ0JvQmAogIC8vINC40Lcg0L/Qu9Cw0L3QsDog0LTQsNC70YzRiNC1IMKrRmlsZSBub3QgZm91bmQ6IHJlcXVpcmVtZW50cy50eHTCuyAo0LrQtdC50YEgc2VhcnhuZy5waW5va2lvKS4KICB0cnl7IGNvbnN0IGV4cHI9U3RyaW5nKHdoZW4pLnJlcGxhY2UoL15ce1x7fFx9XH0kL2csJycpOyByZXR1cm4gISEobmV3IEZ1bmN0aW9uKCdncHUnLCdwbGF0Zm9ybScsJ2FyY2gnLCdhcmdzJywnZXhpc3RzJywnd2hpY2gnLCdrZXJuZWwnLCdwYXRoJywncmV0dXJuICgnK2V4cHIrJyknKShjLmdwdSxjLnBsYXRmb3JtLGMuYXJjaCxjLmFyZ3N8fHt9LGMuZXhpc3RzLGMud2hpY2gsYy5rZXJuZWwscGF0aCkpOyB9Y2F0Y2goZSl7IGlmKGMuX3doZW5FcnJvcnMpIGMuX3doZW5FcnJvcnMucHVzaChTdHJpbmcod2hlbikuc2xpY2UoMCw4MCkrJzogJytlLm1lc3NhZ2UpOyByZXR1cm4gZmFsc2U7IH0gfQoKYXN5bmMgZnVuY3Rpb24gbG9hZFJlY2lwZShmaWxlLCBrZXJuZWwpewogIGxldCBtID0gcnVuSW5TYW5kYm94KGZpbGUsIGtlcm5lbCwgbmV3IFNldChbcGF0aC5yZXNvbHZlKGZpbGUpXSkpOyAgLy8g0LIg0L/QtdGB0L7Rh9C90LjRhtC1LCDQkdCV0JcgcmVxdWlyZSgpCiAgaWYodHlwZW9mIG09PT0nZnVuY3Rpb24nKXsgbSA9IGF3YWl0IG0oa2VybmVsKTsgfSAgIC8vIGFzeW5jKGtlcm5lbCk9Pnt9INGC0L7QttC1CiAgcmV0dXJuIG07Cn0KYXN5bmMgZnVuY3Rpb24gcmVzb2x2ZShyb290LCBlbnRyeSwgYXJncywgZGVwdGgsIG91dCwga2VybmVsKXsKICBpZihkZXB0aD42KSByZXR1cm47CiAgY29uc3QgZmlsZT1wYXRoLnJlc29sdmUocm9vdCxlbnRyeSk7CiAgbGV0IHJlYzsgdHJ5eyByZWM9YXdhaXQgbG9hZFJlY2lwZShmaWxlLGtlcm5lbCk7IH1jYXRjaChlKXsgb3V0Lm1ldGEuZXJyb3JzLnB1c2goZW50cnkrJzogJytlLm1lc3NhZ2UpOyByZXR1cm47IH0KICBpZihyZWMgJiYgcmVjLmRhZW1vbikgb3V0Lm1ldGEuZGFlbW9uPXRydWU7CiAgY29uc3QgcnVuPShyZWMmJnJlYy5ydW4pfHxbXTsKICBjb25zdCBjPXtncHU6a2VybmVsLmdwdSxwbGF0Zm9ybTprZXJuZWwucGxhdGZvcm0sYXJjaDprZXJuZWwuYXJjaCxhcmdzOmFyZ3N8fHt9LGlucHV0OntldmVudDpbJyddfSxjd2Q6cm9vdCxwb3J0Omtlcm5lbC5fZ2V0UG9ydCgpLGV4aXN0czoocCk9Pmtlcm5lbC5leGlzdHMocCksd2hpY2g6KHgpPT5rZXJuZWwud2hpY2goeCksa2VybmVsOmtlcm5lbCxfd2hlbkVycm9yczpvdXQubWV0YS53aGVuRXJyb3JzfTsKICBmb3IoY29uc3Qgc3RlcCBvZiBydW4pewogICAgaWYoIWV2YWxXaGVuKHN0ZXAud2hlbixjKSkgY29udGludWU7CiAgICBjb25zdCBtZXRob2Q9c3RlcC5tZXRob2R8fCcnOwogICAgY29uc3QgcD10bXBsRGVlcChzdGVwLnBhcmFtc3x8e30sey4uLmMscG9ydDprZXJuZWwuX2dldFBvcnQoKX0pOwogICAgaWYobWV0aG9kPT09J3NoZWxsLnJ1bicpewogICAgICBsZXQgbXNncz1wLm1lc3NhZ2U7IGlmKHR5cGVvZiBtc2dzPT09J3N0cmluZycpIG1zZ3M9W21zZ3NdOyBtc2dzPShtc2dzfHxbXSkuZmlsdGVyKG09Pm0mJlN0cmluZyhtKS50cmltKCkpOwogICAgICBpZihtc2dzLmxlbmd0aCkgb3V0LnN0ZXBzLnB1c2goe21ldGhvZDonc2hlbGwucnVuJyxwYXJhbXM6e3ZlbnY6cC52ZW52fHxudWxsLHBhdGg6cC5wYXRofHwnJyxlbnY6cC5lbnZ8fHt9LG1lc3NhZ2U6bXNnc319KTsKICAgIH0gZWxzZSBpZihtZXRob2Q9PT0nc2NyaXB0LnN0YXJ0J3x8bWV0aG9kPT09J3NjcmlwdC5ydW4nKXsKICAgICAgY29uc3QgdXJpPXAudXJpOyBjb25zdCBzdWI9KHN0ZXAucGFyYW1zJiZzdGVwLnBhcmFtcy5wYXJhbXMpfHx7fTsKICAgICAgaWYodXJpJiYvXC5qcyhvbik/JC8udGVzdCh1cmkpKSBhd2FpdCByZXNvbHZlKHJvb3QsdXJpLHN1YixkZXB0aCsxLG91dCxrZXJuZWwpOwogICAgfSBlbHNlIGlmKG1ldGhvZD09PSdmcy5ybScpewogICAgICAvLyDQn9GA0LjQvNC10L3Rj9C10Lwg0KHQoNCQ0JfQoyDQv9GA0Lgg0YDQtdC30L7Qu9Cy0LU6INCy0YHQtSB3aGVuINCy0YvRh9C40YHQu9GP0Y7RgtGB0Y8g0LfQsNGA0LDQvdC10LUsINC4INC/0L7RgdC70LXQtNGD0Y7RidC40LUKICAgICAgLy8gZXhpc3RzKCkg0LTQvtC70LbQvdGLINCy0LjQtNC10YLRjCDRg9C20LUg0L7Rh9C40YnQtdC90L3QvtC1INGB0L7RgdGC0L7Rj9C90LjQtSDigJQg0LjQvdCw0YfQtSDCq2dpdCBjbG9uZSwg0LXRgdC70LgKICAgICAgLy8g0L3QtdGCIGFwcMK7INC/0YDQvtC/0YPRgdC60LDQu9GB0Y8g0LjQty3Qt9CwINCx0LjRgtC+0LPQviDQvtGB0YLQsNGC0LrQsCDQv9GA0L7RiNC70L7QuSDQv9C+0L/Ri9GC0LrQuCAoc2VhcnhuZykuCiAgICAgIHRyeXsgY29uc3QgdD1wYXRoLnJlc29sdmUocm9vdCwgcC5wYXRofHwnJyk7IGlmKHQuc3RhcnRzV2l0aChrZXJuZWwuX3Jvb3QrcmVxdWlyZSgncGF0aCcpLnNlcCl8fHQ9PT1rZXJuZWwuX3Jvb3QpIGZzLnJtU3luYyh0LHtyZWN1cnNpdmU6dHJ1ZSxmb3JjZTp0cnVlfSk7IH1jYXRjaChlKXsgb3V0Lm1ldGEuZXJyb3JzLnB1c2goJ2ZzLnJtOiAnK2UubWVzc2FnZSk7IH0KICAgIH0gZWxzZSBpZihtZXRob2Q9PT0nZnMuZG93bmxvYWQnfHxtZXRob2Q9PT0nZnMubGluayd8fG1ldGhvZD09PSdmcy5jb3B5Jyl7IG91dC5zdGVwcy5wdXNoKHttZXRob2QscGFyYW1zOnB9KTsgfQogIH0KfQooYXN5bmMoKT0+ewogIGNvbnN0IFssLGFwcERpcixlbnRyeSxncHUscGxhdGZvcm0sZml4ZWRQb3J0XT1wcm9jZXNzLmFyZ3Y7CiAgaWYoZ3B1KSBwcm9jZXNzLmVudi5SRUNfR1BVPWdwdTsgaWYocGxhdGZvcm0pIHByb2Nlc3MuZW52LlJFQ19QTEFURk9STT1wbGF0Zm9ybTsKICBjb25zdCBrZXJuZWw9bWFrZUtlcm5lbChhcHBEaXJ8fCcuJywgZml4ZWRQb3J0P3BhcnNlSW50KGZpeGVkUG9ydCk6bnVsbCk7CiAgYXdhaXQga2VybmVsLnBvcnQoKTsgIC8vINC30LDRhNC40LrRgdC40YDQvtCy0LDRgtGMINC/0L7RgNGCCiAgY29uc3Qgb3V0PXtzdGVwczpbXSxtZXRhOntkYWVtb246ZmFsc2UsZXJyb3JzOltdLHdoZW5FcnJvcnM6W119fTsKICBhd2FpdCByZXNvbHZlKGFwcERpcnx8Jy4nLCBlbnRyeXx8J2luc3RhbGwuanMnLCB7fSwgMCwgb3V0LCBrZXJuZWwpOwogIGNvbnNvbGUubG9nKEpTT04uc3RyaW5naWZ5KHtncHU6a2VybmVsLmdwdSxwbGF0Zm9ybTprZXJuZWwucGxhdGZvcm0scG9ydDprZXJuZWwuX2dldFBvcnQoKSxkYWVtb246b3V0Lm1ldGEuZGFlbW9uLGVycm9yczpvdXQubWV0YS5lcnJvcnMsd2hlbkVycm9yczpvdXQubWV0YS53aGVuRXJyb3JzLHN0ZXBzOm91dC5zdGVwc30sbnVsbCwyKSk7Cn0pKCk7Cg=="""))
    entry="install.js" if os.path.exists(os.path.join(root,"install.js")) else "pinokio.js"
    rr=subprocess.run([node,resolve_js,root,entry],capture_output=True,text=True,timeout=120)
    resolved=None
    try: resolved=json.loads(rr.stdout)
    except Exception: resolved=None
    if resolved is None:
        _se=(rr.stderr or rr.stdout or "")
        return err("резолв не удался после проверки Node.js: "+_se[-150:])
    steps=resolved.get("steps",[])
    if not steps:
        _why="; ".join((resolved.get("errors") or [])+(resolved.get("whenErrors") or []))[:200]
        return err("Рецепт приложения не дал ни одного шага для этой платформы"+(" ("+_why+")" if _why else "")+
                   ". Это ошибка на нашей стороне, не ваша — напишите нам, приложив это сообщение.")
    # 2.5 РАНТАЙМ-БУТСТРАП: доставить пакет-менеджеры, которые нужны рецепту (как встроенные у Pinokio)
    def _ensure_runtime(steps):
        import platform
        allmsg = " ".join(m for st in steps if st.get("method")=="shell.run" for m in (st.get("params",{}).get("message") or []))
        got, extra_path = [], []
        # uv — быстрый pip (user-space, без админа)
        if "uv " in allmsg:
            uv, uv_state = path_or_error("uv", repair=True)
            if not uv:
                return None, [], got, uv_state.get("message") or "uv недоступен"
            if uv_state.get("changed"): got.append("uv")
            extra_path.append(os.path.dirname(uv))
        # conda — Miniconda (user-space, без админа)
        if ("conda " in allmsg or "conda activate" in allmsg):
            conda = shutil.which("conda") or os.path.expanduser("~/miniconda3/bin/conda")
            if not os.path.exists(conda):
                sysn = "MacOSX" if platform.system()=="Darwin" else "Linux"
                arch = "arm64" if platform.machine() in ("arm64","aarch64") else "x86_64"
                url = "https://repo.anaconda.com/miniconda/Miniconda3-latest-%s-%s.sh" % (sysn, arch)
                sh = os.path.expanduser("~/.extella_miniconda.sh")
                try:
                    urllib.request.urlretrieve(url, sh)
                    subprocess.run(["bash", sh, "-b", "-p", os.path.expanduser("~/miniconda3")], capture_output=True, text=True, timeout=900)
                    got.append("miniconda")
                except Exception: pass
            extra_path.append(os.path.expanduser("~/miniconda3/bin"))
        # node/npm — нужен brew (админ, разовый шаг установщика) — сами не ставим
        node_needed = any(t in allmsg for t in ("npm ","npx ","node ","pnpm ","yarn "))
        if node_needed:
            checked_node, checked_state = path_or_error("node", repair=True)
            if not checked_node:
                return None, [p for p in extra_path if p], got, checked_state.get("message") or "Node.js недоступен"
            extra_path.append(os.path.dirname(checked_node))
        return True, [p for p in extra_path if p], got, ""

    ok_rt, RT_PATH, rt_got, rt_err = _ensure_runtime(steps)
    if ok_rt is None:
        return err(rt_err)

    # 3. исполнить shell-шаги в venv
    def _best_py():
        checked_python, _state = path_or_error("python", repair=False)
        return checked_python or sys.executable
    def venv_py(vp):
        vabs=os.path.normpath(os.path.join(root,vp)); py=os.path.join(vabs,"bin","python")
        if not os.path.exists(py): subprocess.run([_best_py(),"-m","venv",vabs],capture_output=True,text=True,timeout=120)
        return py
    done=0
    for st in steps:
        meth=st.get("method")
        if meth=="fs.rm":
            # рецепты чистят битые остатки прошлых попыток (searxng: rm app, если
            # в нём нет requirements.txt) — без этого клон пропускался «app уже есть»
            _tgt=os.path.normpath(os.path.join(root,(st.get("params",{}) or {}).get("path","") or ""))
            if _tgt.startswith(os.path.normpath(root)+os.sep):  # только внутри папки приложения
                shutil.rmtree(_tgt, ignore_errors=True)
            continue
        if meth!="shell.run": continue
        p=st.get("params",{}); cwd=os.path.normpath(os.path.join(root,p.get("path","") or ""))
        os.makedirs(cwd,exist_ok=True)
        env=dict(os.environ)
        if RT_PATH: env["PATH"]=os.pathsep.join(RT_PATH)+os.pathsep+env.get("PATH","")
        if p.get("venv"):
            vpy=venv_py(p["venv"]); env["VIRTUAL_ENV"]=os.path.dirname(os.path.dirname(vpy))
            env["PATH"]=os.path.join(env["VIRTUAL_ENV"],"bin")+os.pathsep+env.get("PATH","")
            env.setdefault("UV_SYSTEM_PYTHON","0")
        for m in (p.get("message") or []):
            m2=m.replace("uv pip","pip") if not shutil.which("uv") else m  # фолбэк если нет uv
            # идемпотентность: git clone во внутр. папку падает на повторе → пропускаем, если папка уже склонирована
            gc=re.match(r"\s*git\s+clone\b.*?\s(\S+)\s*$", m2)
            if gc:
                tgt=os.path.join(cwd, gc.group(1))
                if os.path.isdir(os.path.join(tgt,".git")):
                    continue
                shutil.rmtree(tgt, ignore_errors=True)  # чистим частичный клон
            r=subprocess.run(m2,shell=True,cwd=cwd,env=env,capture_output=True,text=True,timeout=900)
            if r.returncode!=0:
                _tail=((r.stderr or r.stdout or "").strip())[-200:]
                return err("Установка остановилась на шаге рецепта: «"+m2[:80]+"». Причина: "+
                           (_tail or "команда вернула ошибку")+
                           ". Что делать: нажмите «Установить» ещё раз — шаги продолжатся с места остановки; если повторится, пришлите нам это сообщение целиком.")
        done+=1
    # 4. реестр (старт делаем отдельно через app_start)
    def _reg_path(aid):
        # Имя файла реестра — ПЛОСКОЕ, зеркало тулбарного _safeIdOf (посимвольно,
        # без схлопывания): id со слэшем (cocktailpeanut/searxng.pinokio) писал
        # манифест во вложенную папку, где тулбар его не ищет.
        return os.path.expanduser("~/extella-plugins/_registry/"+re.sub(r"[^a-zA-Z0-9]","_",aid)+".json")
    reg=_reg_path(app_id)
    os.makedirs(os.path.dirname(reg),exist_ok=True)
    # миграция: убрать легаси-запись по дословному app_id (вложенную при слэше)
    _legacy=os.path.expanduser("~/extella-plugins/_registry/"+app_id+".json")
    if _legacy!=reg and os.path.isfile(_legacy):
        try:
            os.remove(_legacy)
            _ld=os.path.dirname(_legacy)
            if _ld.startswith(os.path.expanduser("~/extella-plugins/_registry/")) and not os.listdir(_ld): os.rmdir(_ld)
        except Exception: pass
    man={"id":app_id,"name":app_id,"type":"recipe","mode":"app",
         "app":{"root":root,"repo":repo},"experts":[],"installed":True,
         "ui":{"type":"local_server","rootPath":root,"mainFile":"index.html","openInBrowser":False}}
    open(reg,"w",encoding="utf-8").write(json.dumps(man,ensure_ascii=False,indent=2))
    return json.dumps({"status":"success","app_id":app_id,"root":root,"install_steps":done,
                       "gpu":resolved.get("gpu"),"platform":resolved.get("platform"),
                       "runtimes":rt_got,"message":"установлено по рецепту"}, ensure_ascii=False)
