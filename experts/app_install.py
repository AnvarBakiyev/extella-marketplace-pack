# expert: app_install
# description: Ставит приложение по рецепту (формат Pinokio, БЕЗ LLM): клонирует репо → резолвит install.js через Node (под GPU/платформу) → исполняет shell-шаги в изолир. venv → пишет реестр плагина + старт. Node нужен (разовый brew). Возвращает {status, plugin_id, steps}.
def app_install(repo="", app_id="", branch="main"):
    import os, json, subprocess, sys, tempfile, shutil, base64, re
    def err(m): return json.dumps({"status":"error","message":m,"app_id":app_id}, ensure_ascii=False)
    repo=(repo or "").strip()
    if not app_id:
        app_id = re.sub(r"[^a-z0-9]+","_", (repo.rstrip("/").split("/")[-1] or "app").lower())
    root = os.path.expanduser("~/extella-apps/"+app_id)
    # node?
    node = shutil.which("node") or next((p for p in ["/opt/homebrew/bin/node","/usr/local/bin/node"] if os.path.exists(p)), None)
    if not node: return err("нужен Node (разовый Homebrew-шаг установщика)")
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
    open(resolve_js,"wb").write(base64.b64decode("""Ly8g0KDQtdC30L7Qu9Cy0LXRgCBQaW5va2lvLdGA0LXRhtC10L/RgtC+0LIg4oaSINC/0LvQvtGB0LrQuNC1IHNoZWxsLnJ1biDRiNCw0LPQuCArINC/0L7RgNGCICjQtNC10YLQtdGA0LzQuNC90LjRgNC+0LLQsNC90L3Qviwg0YHQstC+0Lkg0LzQuNC90Lgta2VybmVsKS4KLy8gbm9kZSByZWNpcGVfcmVzb2x2ZS5qcyA8YXBwX2Rpcj4gPGVudHJ5LmpzPiBbZ3B1XSBbcGxhdGZvcm1dIFtmaXhlZF9wb3J0XQpjb25zdCBwYXRoID0gcmVxdWlyZSgncGF0aCcpOwpjb25zdCBvcyA9IHJlcXVpcmUoJ29zJyk7CmNvbnN0IG5ldCA9IHJlcXVpcmUoJ25ldCcpOwpjb25zdCBjcCA9IHJlcXVpcmUoJ2NoaWxkX3Byb2Nlc3MnKTsKY29uc3QgZnMgPSByZXF1aXJlKCdmcycpOwpjb25zdCB2bSA9IHJlcXVpcmUoJ3ZtJyk7CgovLyDilIDilIAg0J/QldCh0J7Qp9Cd0JjQptCQIOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgOKUgAovLyDQoNC10YbQtdC/0YLRiyDigJQg0YfRg9C20L7QuSBKUyDQuNC3INGB0LrQu9C+0L3QuNGA0L7QstCw0L3QvdC+0LPQviDRgNC10L/Qvi4g0J3QldCb0KzQl9CvINC40YHQv9C+0LvQvdGP0YLRjCDQtdCz0L4g0YEg0L/QvtC70L3Ri9C80LgKLy8g0L/RgNCw0LLQsNC80LggTm9kZSAoZnMvY2hpbGRfcHJvY2Vzcy/RgdC10YLRjC9wcm9jZXNzLmVudi3RgdC10LrRgNC10YLRiykuINCT0YDRg9C30LjQvCDRgNC10YbQtdC/0YIg0LIKLy8gdm0t0LrQvtC90YLQtdC60YHRgjog0LTQvtGB0YLRg9C/0L3RiyDRgtC+0LvRjNC60L4gbW9kdWxlL2V4cG9ydHMsINCx0LXQt9Cy0YDQtdC00L3Ri9C1IHBhdGh8b3MsINC4IHJlcXVpcmUKLy8g0YHQvtGB0LXQtNC90LjRhSAuanMg0YDQtdGG0LXQv9GC0L7QsiAo0YLQvtC20LUg0LIg0L/QtdGB0L7Rh9C90LjRhtC1KS4g0JLRgdGRINC+0YHRgtCw0LvRjNC90L7QtSAoZnMsIGNoaWxkX3Byb2Nlc3MsCi8vIG5ldCwgaHR0cOKApikg4oCUINC30LDQsdC70L7QutC40YDQvtCy0LDQvdC+LiDQntC/0LDRgdC90YvQtSDQvtC/0LXRgNCw0YbQuNC4ICh3aGljaC9leGlzdHMpINC00LXQu9Cw0LXRgiDQndCQ0KgKLy8ga2VybmVsLCDQsCDQvdC1INGA0LXRhtC10L/Rgi4KY29uc3QgU0FGRV9NT0RVTEVTID0geyBwYXRoOiBwYXRoLCBvczogeyBwbGF0Zm9ybTooKT0+cHJvY2Vzcy5wbGF0Zm9ybSwgYXJjaDooKT0+b3MuYXJjaCgpLCBob21lZGlyOigpPT5vcy5ob21lZGlyKCksIGNwdXM6KCk9Pm9zLmNwdXMoKSwgdG90YWxtZW06KCk9Pm9zLnRvdGFsbWVtKCksIHR5cGU6KCk9Pm9zLnR5cGUoKSB9IH07CmZ1bmN0aW9uIG1ha2VTYW5kYm94UmVxdWlyZShiYXNlRGlyLCBrZXJuZWwsIHNlZW4pewogIHJldHVybiBmdW5jdGlvbiBzYW5kYm94UmVxdWlyZShzcGVjKXsKICAgIGlmKFNBRkVfTU9EVUxFU1tzcGVjXSkgcmV0dXJuIFNBRkVfTU9EVUxFU1tzcGVjXTsKICAgIGlmKC9eXC5cLj9cLy8udGVzdChzcGVjKSl7ICAgICAgICAgICAgICAgICAgICAgICAgIC8vINGB0L7RgdC10LTQvdC40Lkg0YTQsNC50Lst0YDQtdGG0LXQv9GCCiAgICAgIGxldCBmID0gcGF0aC5yZXNvbHZlKGJhc2VEaXIsIHNwZWMpOwogICAgICBpZighL1wuanMob24pPyQvLnRlc3QoZikgJiYgZnMuZXhpc3RzU3luYyhmKycuanMnKSkgZj1mKycuanMnOwogICAgICBpZihmLmVuZHNXaXRoKCcuanNvbicpKXsgdHJ5eyByZXR1cm4gSlNPTi5wYXJzZShmcy5yZWFkRmlsZVN5bmMoZiwndXRmOCcpKTsgfWNhdGNoKGUpeyByZXR1cm4ge307IH0gfQogICAgICBpZighZi5zdGFydHNXaXRoKGtlcm5lbC5fcm9vdCkpIHRocm93IG5ldyBFcnJvcignc2FuZGJveDog0L/Rg9GC0Ywg0LLQvdC1INC/0YDQuNC70L7QttC10L3QuNGPOiAnK3NwZWMpOwogICAgICBpZihzZWVuLmhhcyhmKSkgcmV0dXJuIHt9OyAgICAgICAgICAgICAgICAgICAgICAgIC8vINC30LDRidC40YLQsCDQvtGCINGG0LjQutC70L7QsgogICAgICBzZWVuLmFkZChmKTsKICAgICAgcmV0dXJuIHJ1bkluU2FuZGJveChmLCBrZXJuZWwsIHNlZW4pOwogICAgfQogICAgdGhyb3cgbmV3IEVycm9yKCdzYW5kYm94OiDQvNC+0LTRg9C70Ywg0LfQsNC/0YDQtdGJ0ZHQvTogJytzcGVjKTsgLy8gZnMvY2hpbGRfcHJvY2Vzcy9uZXQvaHR0cC/igKYKICB9Owp9CmZ1bmN0aW9uIHJ1bkluU2FuZGJveChmaWxlLCBrZXJuZWwsIHNlZW4pewogIGNvbnN0IGNvZGUgPSBmcy5yZWFkRmlsZVN5bmMoZmlsZSwgJ3V0ZjgnKTsKICBjb25zdCBzYW5kYm94ID0gewogICAgbW9kdWxlOntleHBvcnRzOnt9fSwgZXhwb3J0czp7fSwKICAgIHJlcXVpcmU6IG1ha2VTYW5kYm94UmVxdWlyZShwYXRoLmRpcm5hbWUoZmlsZSksIGtlcm5lbCwgc2VlbiksCiAgICBjb25zb2xlOiB7IGxvZzooKT0+e30sIGVycm9yOigpPT57fSwgd2FybjooKT0+e30gfSwKICAgIC8vINCx0LXQt9Cy0YDQtdC00L3Ri9C5IHByb2Nlc3M6INGC0L7Qu9GM0LrQviDQv9C70LDRgtGE0L7RgNC80LAv0LDRgNGFLCDQkdCV0JcgZW52L2V4aXQvY3dkLdC30LDQv9C40YHQuC9hcmd2CiAgICBwcm9jZXNzOiB7IHBsYXRmb3JtOnByb2Nlc3MucGxhdGZvcm0sIGFyY2g6b3MuYXJjaCgpLCBlbnY6e30sIHZlcnNpb246cHJvY2Vzcy52ZXJzaW9uIH0sCiAgICBCdWZmZXI6IEJ1ZmZlciwgc2V0VGltZW91dDooKT0+e30sIGNsZWFyVGltZW91dDooKT0+e30sIF9fZGlybmFtZTpwYXRoLmRpcm5hbWUoZmlsZSksIF9fZmlsZW5hbWU6ZmlsZSwKICB9OwogIHNhbmRib3guZ2xvYmFsID0gc2FuZGJveDsgc2FuZGJveC5nbG9iYWxUaGlzID0gc2FuZGJveDsKICB2bS5jcmVhdGVDb250ZXh0KHNhbmRib3gpOwogIHZtLnJ1bkluQ29udGV4dChjb2RlLCBzYW5kYm94LCB7IGZpbGVuYW1lOmZpbGUsIHRpbWVvdXQ6NTAwMCB9KTsgICAvLyA10YEg0L/QvtGC0L7Qu9C+0Log0L3QsCDQt9Cw0LPRgNGD0LfQutGDCiAgY29uc3QgbWUgPSBzYW5kYm94Lm1vZHVsZS5leHBvcnRzOyAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAvLyDRhNGD0L3QutGG0LjRjyDQmNCb0Jgg0L3QtdC/0YPRgdGC0L7QuSDQvtCx0YrQtdC60YIg4oaSINGN0YLQviDQuCDQtdGB0YLRjCDRgNC10YbQtdC/0YIKICBpZih0eXBlb2YgbWU9PT0nZnVuY3Rpb24nIHx8IChtZSAmJiBPYmplY3Qua2V5cyhtZSkubGVuZ3RoKSkgcmV0dXJuIG1lOwogIHJldHVybiBzYW5kYm94LmV4cG9ydHM7Cn0KCmZ1bmN0aW9uIGRldGVjdEdwdSgpeyBpZihwcm9jZXNzLnBsYXRmb3JtPT09J2RhcndpbicpIHJldHVybiBvcy5hcmNoKCk9PT0nYXJtNjQnPydhcHBsZSc6J2NwdSc7CiAgdHJ5eyBjcC5leGVjU3luYygnbnZpZGlhLXNtaScse3N0ZGlvOidpZ25vcmUnfSk7IHJldHVybiAnbnZpZGlhJzsgfWNhdGNoKGUpe30gcmV0dXJuICdjcHUnOyB9CmZ1bmN0aW9uIGZyZWVQb3J0U3luYyhwcmVmKXsKICBpZihwcmVmKSByZXR1cm4gcHJlZjsKICB0cnl7IGNvbnN0IHM9bmV0LmNyZWF0ZVNlcnZlcigpOyByZXR1cm4gbmV3IFByb21pc2UocmVzPT57IHMubGlzdGVuKDAsKCk9Pntjb25zdCBwPXMuYWRkcmVzcygpLnBvcnQ7IHMuY2xvc2UoKCk9PnJlcyhwKSk7fSk7IH0pOyB9CiAgY2F0Y2goZSl7IHJldHVybiA3ODYwOyB9Cn0KCi8vINCc0LjQvdC4LWtlcm5lbCAo0YLQviwg0YfRgtC+INGA0LXRhtC10L/RgtGLINC20LTRg9GCINC+0YIgUGlub2tpbykKZnVuY3Rpb24gbWFrZUtlcm5lbChyb290LCBmb3JjZWRQb3J0KXsKICBjb25zdCBncHUgPSBwcm9jZXNzLmVudi5SRUNfR1BVIHx8IGRldGVjdEdwdSgpOwogIGNvbnN0IHBsYXRmb3JtID0gcHJvY2Vzcy5lbnYuUkVDX1BMQVRGT1JNIHx8IHByb2Nlc3MucGxhdGZvcm07CiAgbGV0IF9wb3J0ID0gZm9yY2VkUG9ydCB8fCBudWxsOwogIHJldHVybiB7CiAgICBfcm9vdDogcGF0aC5yZXNvbHZlKHJvb3QpLAogICAgZ3B1LCBwbGF0Zm9ybSwgYXJjaDogb3MuYXJjaCgpLCBob21lZGlyOiBvcy5ob21lZGlyKCksCiAgICBwb3J0OiBhc3luYyAoKSA9PiB7IGlmKCFfcG9ydCl7IF9wb3J0ID0gYXdhaXQgZnJlZVBvcnRTeW5jKG51bGwpOyB9IHJldHVybiBfcG9ydDsgfSwKICAgIHBhdGg6ICguLi5hKSA9PiBwYXRoLnJlc29sdmUocm9vdCwgLi4uYSksCiAgICB3aGljaDogKGMpID0+IHsgdHJ5eyByZXR1cm4gY3AuZXhlY1N5bmMoKHByb2Nlc3MucGxhdGZvcm09PT0nd2luMzInPyd3aGVyZSAnOid3aGljaCAnKStjKS50b1N0cmluZygpLnRyaW0oKS5zcGxpdCgnXG4nKVswXTsgfWNhdGNoKGUpeyByZXR1cm4gbnVsbDsgfSB9LAogICAgZXhpc3RzOiAocCkgPT4gcmVxdWlyZSgnZnMnKS5leGlzdHNTeW5jKHBhdGgucmVzb2x2ZShyb290LHApKSwKICAgIGFwaToge30sIG1lbW9yeToge30sIGJpbjogeyBwYXRoOiAoKT0+cGF0aC5qb2luKG9zLmhvbWVkaXIoKSwncGlub2tpbycsJ2JpbicpIH0sCiAgICBfZ2V0UG9ydDogKCkgPT4gX3BvcnQsCiAgfTsKfQoKZnVuY3Rpb24gdG1wbCh2YWwsYyl7IGlmKHR5cGVvZiB2YWwhPT0nc3RyaW5nJ3x8IXZhbC5pbmNsdWRlcygne3snKSkgcmV0dXJuIHZhbDsKICByZXR1cm4gdmFsLnJlcGxhY2UoL1x7XHsoW1xzXFNdKj8pXH1cfS9nLChfLGUpPT57IHRyeXsgY29uc3QgZj1uZXcgRnVuY3Rpb24oJ2dwdScsJ3BsYXRmb3JtJywnYXJjaCcsJ2FyZ3MnLCdpbnB1dCcsJ2N3ZCcsJ3BvcnQnLCdyZXR1cm4gKCcrZSsnKScpOwogICAgY29uc3Qgcj1mKGMuZ3B1LGMucGxhdGZvcm0sYy5hcmNoLGMuYXJnc3x8e30sYy5pbnB1dHx8e30sYy5jd2QsYy5wb3J0KTsgcmV0dXJuIChyPT1udWxsKT8nJzpTdHJpbmcocik7fWNhdGNoKHgpe3JldHVybiAnJzt9IH0pOyB9CmZ1bmN0aW9uIHRtcGxEZWVwKG8sYyl7IGlmKEFycmF5LmlzQXJyYXkobykpIHJldHVybiBvLm1hcCh4PT50bXBsRGVlcCh4LGMpKS5maWx0ZXIoeD0+eCE9PScnJiZ4IT09bnVsbCk7CiAgaWYobyYmdHlwZW9mIG89PT0nb2JqZWN0Jyl7Y29uc3Qgcj17fTtmb3IoY29uc3QgayBpbiBvKXJba109dG1wbERlZXAob1trXSxjKTtyZXR1cm4gcjt9IHJldHVybiB0bXBsKG8sYyk7IH0KZnVuY3Rpb24gZXZhbFdoZW4od2hlbixjKXsgaWYoIXdoZW4pIHJldHVybiB0cnVlOwogIHRyeXsgY29uc3QgZXhwcj1TdHJpbmcod2hlbikucmVwbGFjZSgvXlx7XHt8XH1cfSQvZywnJyk7IHJldHVybiAhIShuZXcgRnVuY3Rpb24oJ2dwdScsJ3BsYXRmb3JtJywnYXJjaCcsJ2FyZ3MnLCdyZXR1cm4gKCcrZXhwcisnKScpKGMuZ3B1LGMucGxhdGZvcm0sYy5hcmNoLGMuYXJnc3x8e30pKTsgfWNhdGNoKGUpeyByZXR1cm4gZmFsc2U7IH0gfQoKYXN5bmMgZnVuY3Rpb24gbG9hZFJlY2lwZShmaWxlLCBrZXJuZWwpewogIGxldCBtID0gcnVuSW5TYW5kYm94KGZpbGUsIGtlcm5lbCwgbmV3IFNldChbcGF0aC5yZXNvbHZlKGZpbGUpXSkpOyAgLy8g0LIg0L/QtdGB0L7Rh9C90LjRhtC1LCDQkdCV0JcgcmVxdWlyZSgpCiAgaWYodHlwZW9mIG09PT0nZnVuY3Rpb24nKXsgbSA9IGF3YWl0IG0oa2VybmVsKTsgfSAgIC8vIGFzeW5jKGtlcm5lbCk9Pnt9INGC0L7QttC1CiAgcmV0dXJuIG07Cn0KYXN5bmMgZnVuY3Rpb24gcmVzb2x2ZShyb290LCBlbnRyeSwgYXJncywgZGVwdGgsIG91dCwga2VybmVsKXsKICBpZihkZXB0aD42KSByZXR1cm47CiAgY29uc3QgZmlsZT1wYXRoLnJlc29sdmUocm9vdCxlbnRyeSk7CiAgbGV0IHJlYzsgdHJ5eyByZWM9YXdhaXQgbG9hZFJlY2lwZShmaWxlLGtlcm5lbCk7IH1jYXRjaChlKXsgb3V0Lm1ldGEuZXJyb3JzLnB1c2goZW50cnkrJzogJytlLm1lc3NhZ2UpOyByZXR1cm47IH0KICBpZihyZWMgJiYgcmVjLmRhZW1vbikgb3V0Lm1ldGEuZGFlbW9uPXRydWU7CiAgY29uc3QgcnVuPShyZWMmJnJlYy5ydW4pfHxbXTsKICBjb25zdCBjPXtncHU6a2VybmVsLmdwdSxwbGF0Zm9ybTprZXJuZWwucGxhdGZvcm0sYXJjaDprZXJuZWwuYXJjaCxhcmdzOmFyZ3N8fHt9LGlucHV0OntldmVudDpbJyddfSxjd2Q6cm9vdCxwb3J0Omtlcm5lbC5fZ2V0UG9ydCgpfTsKICBmb3IoY29uc3Qgc3RlcCBvZiBydW4pewogICAgaWYoIWV2YWxXaGVuKHN0ZXAud2hlbixjKSkgY29udGludWU7CiAgICBjb25zdCBtZXRob2Q9c3RlcC5tZXRob2R8fCcnOwogICAgY29uc3QgcD10bXBsRGVlcChzdGVwLnBhcmFtc3x8e30sey4uLmMscG9ydDprZXJuZWwuX2dldFBvcnQoKX0pOwogICAgaWYobWV0aG9kPT09J3NoZWxsLnJ1bicpewogICAgICBsZXQgbXNncz1wLm1lc3NhZ2U7IGlmKHR5cGVvZiBtc2dzPT09J3N0cmluZycpIG1zZ3M9W21zZ3NdOyBtc2dzPShtc2dzfHxbXSkuZmlsdGVyKG09Pm0mJlN0cmluZyhtKS50cmltKCkpOwogICAgICBpZihtc2dzLmxlbmd0aCkgb3V0LnN0ZXBzLnB1c2goe21ldGhvZDonc2hlbGwucnVuJyxwYXJhbXM6e3ZlbnY6cC52ZW52fHxudWxsLHBhdGg6cC5wYXRofHwnJyxlbnY6cC5lbnZ8fHt9LG1lc3NhZ2U6bXNnc319KTsKICAgIH0gZWxzZSBpZihtZXRob2Q9PT0nc2NyaXB0LnN0YXJ0J3x8bWV0aG9kPT09J3NjcmlwdC5ydW4nKXsKICAgICAgY29uc3QgdXJpPXAudXJpOyBjb25zdCBzdWI9KHN0ZXAucGFyYW1zJiZzdGVwLnBhcmFtcy5wYXJhbXMpfHx7fTsKICAgICAgaWYodXJpJiYvXC5qcyhvbik/JC8udGVzdCh1cmkpKSBhd2FpdCByZXNvbHZlKHJvb3QsdXJpLHN1YixkZXB0aCsxLG91dCxrZXJuZWwpOwogICAgfSBlbHNlIGlmKG1ldGhvZD09PSdmcy5kb3dubG9hZCd8fG1ldGhvZD09PSdmcy5saW5rJ3x8bWV0aG9kPT09J2ZzLmNvcHknKXsgb3V0LnN0ZXBzLnB1c2goe21ldGhvZCxwYXJhbXM6cH0pOyB9CiAgfQp9Cihhc3luYygpPT57CiAgY29uc3QgWywsYXBwRGlyLGVudHJ5LGdwdSxwbGF0Zm9ybSxmaXhlZFBvcnRdPXByb2Nlc3MuYXJndjsKICBpZihncHUpIHByb2Nlc3MuZW52LlJFQ19HUFU9Z3B1OyBpZihwbGF0Zm9ybSkgcHJvY2Vzcy5lbnYuUkVDX1BMQVRGT1JNPXBsYXRmb3JtOwogIGNvbnN0IGtlcm5lbD1tYWtlS2VybmVsKGFwcERpcnx8Jy4nLCBmaXhlZFBvcnQ/cGFyc2VJbnQoZml4ZWRQb3J0KTpudWxsKTsKICBhd2FpdCBrZXJuZWwucG9ydCgpOyAgLy8g0LfQsNGE0LjQutGB0LjRgNC+0LLQsNGC0Ywg0L/QvtGA0YIKICBjb25zdCBvdXQ9e3N0ZXBzOltdLG1ldGE6e2RhZW1vbjpmYWxzZSxlcnJvcnM6W119fTsKICBhd2FpdCByZXNvbHZlKGFwcERpcnx8Jy4nLCBlbnRyeXx8J2luc3RhbGwuanMnLCB7fSwgMCwgb3V0LCBrZXJuZWwpOwogIGNvbnNvbGUubG9nKEpTT04uc3RyaW5naWZ5KHtncHU6a2VybmVsLmdwdSxwbGF0Zm9ybTprZXJuZWwucGxhdGZvcm0scG9ydDprZXJuZWwuX2dldFBvcnQoKSxkYWVtb246b3V0Lm1ldGEuZGFlbW9uLGVycm9yczpvdXQubWV0YS5lcnJvcnMsc3RlcHM6b3V0LnN0ZXBzfSxudWxsLDIpKTsKfSkoKTsK"""))
    entry="install.js" if os.path.exists(os.path.join(root,"install.js")) else "pinokio.js"
    rr=subprocess.run([node,resolve_js,root,entry],capture_output=True,text=True,timeout=120)
    try: resolved=json.loads(rr.stdout)
    except Exception: return err("резолв не удался: "+(rr.stderr or rr.stdout or "")[-150:])
    steps=resolved.get("steps",[])
    # 2.5 РАНТАЙМ-БУТСТРАП: доставить пакет-менеджеры, которые нужны рецепту (как встроенные у Pinokio)
    def _ensure_runtime(steps):
        import shutil, platform
        allmsg = " ".join(m for st in steps if st.get("method")=="shell.run" for m in (st.get("params",{}).get("message") or []))
        got, extra_path = [], []
        # uv — быстрый pip (user-space, без админа)
        if "uv " in allmsg:
            uv = shutil.which("uv") or os.path.expanduser("~/.local/bin/uv")
            if not os.path.exists(uv):
                subprocess.run([sys.executable,"-m","pip","install","-q","uv"], capture_output=True, text=True, timeout=180)
                got.append("uv")
            uvbin = os.path.dirname(shutil.which("uv") or "") or os.path.dirname(sys.executable)
            extra_path.append(uvbin)
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
        if node_needed and not (shutil.which("node") or os.path.exists("/opt/homebrew/bin/node")):
            return None, [p for p in extra_path if p], got, "нужен Node (разовый Homebrew-шаг установщика) — рецепт использует npm/node"
        return True, [p for p in extra_path if p], got, ""

    ok_rt, RT_PATH, rt_got, rt_err = _ensure_runtime(steps)
    if ok_rt is None:
        return err(rt_err)

    # 3. исполнить shell-шаги в venv
    def venv_py(vp):
        vabs=os.path.normpath(os.path.join(root,vp)); py=os.path.join(vabs,"bin","python")
        if not os.path.exists(py): subprocess.run([sys.executable,"-m","venv",vabs],capture_output=True,text=True,timeout=120)
        return py
    done=0
    for st in steps:
        if st.get("method")!="shell.run": continue
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
                return err("шаг упал: "+m2[:70]+" | "+(r.stderr or "")[-120:])
        done+=1
    # 4. реестр (старт делаем отдельно через app_start)
    reg=os.path.expanduser("~/extella-plugins/_registry/"+app_id+".json")
    os.makedirs(os.path.dirname(reg),exist_ok=True)
    man={"id":app_id,"name":app_id,"type":"recipe","mode":"app",
         "app":{"root":root,"repo":repo},"experts":[],"installed":True,
         "ui":{"type":"local_server","rootPath":root,"mainFile":"index.html","openInBrowser":False}}
    open(reg,"w",encoding="utf-8").write(json.dumps(man,ensure_ascii=False,indent=2))
    return json.dumps({"status":"success","app_id":app_id,"root":root,"install_steps":done,
                       "gpu":resolved.get("gpu"),"platform":resolved.get("platform"),
                       "runtimes":rt_got,"message":"установлено по рецепту"}, ensure_ascii=False)
