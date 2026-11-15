#!/usr/bin/env python3
"""CI-friendly assemble: same as assemble.py but paths come from env vars."""
import os
import plistlib
import shutil
import subprocess
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
if os.path.basename(HERE) == 'github_actions':
    HERE = os.path.dirname(HERE)

XC = os.environ.get('PYTHON_XCFRAMEWORK', os.path.join(HERE, 'deps', 'Python.xcframework'))
SLICE = os.path.join(XC, 'ios-arm64')
# Prefer system python3 if uv/python 3.14 not available
def find_python():
    for cmd in (['uv', 'python', 'find', '3.14'], ['python3.14'], ['python3']):
        try:
            if cmd[0] == 'uv':
                return subprocess.check_output(cmd, text=True).strip()
            out = subprocess.check_output(cmd + ['-c', 'import sys; print(sys.executable)'], text=True).strip()
            if out:
                return out
        except Exception:
            continue
    return sys.executable

PY314 = os.environ.get('HOST_PYTHON', find_python())
LDID = os.environ.get('LDID', 'ldid')
YTDLP_ZIP = os.environ.get('YTDLP_ZIP', os.path.join(HERE, 'Resources', 'yt-dlp.zip'))
PKGS = os.environ.get('APP_PACKAGES', os.path.join(HERE, 'deps', 'app_packages'))
BUNDLE_ID = 'com.t4mag0.vidgrab'

STAGE = os.path.join(HERE, 'stage')
APP = os.path.join(STAGE, 'Payload', 'VidGrab.app')
OUT = os.path.join(HERE, 'VidGrab.ipa')

DROP_STDLIB = {'test', 'idlelib', 'tkinter', 'turtledemo', 'ensurepip', 'pydoc_data', '__phello__',
               'turtle.py', 'lib2to3', 'venv'}
DROP_DYNLOAD_PREFIX = ('_test', '_ctypes_test', 'xx', '_xxtestfuzz', '_remote_debugging')


def run(*cmd):
    print('+', ' '.join(cmd), flush=True)
    subprocess.run(cmd, check=True)


def main():
    print('XC=', XC)
    print('PKGS=', PKGS)
    print('YTDLP_ZIP=', YTDLP_ZIP)
    print('LDID=', LDID)
    print('PY=', PY314)

    if not os.path.isdir(os.path.join(SLICE, 'Python.framework')):
        print('ERROR: Python.framework not found under', SLICE, file=sys.stderr)
        return 1
    if not os.path.isdir(PKGS):
        print('ERROR: app_packages not found at', PKGS, file=sys.stderr)
        return 1

    app_obj = os.path.join(HERE, '.theos/obj/VidGrab.app')
    if not os.path.isdir(app_obj):
        print('ERROR: compiled app not found at', app_obj, file=sys.stderr)
        return 1

    shutil.rmtree(STAGE, ignore_errors=True)
    os.makedirs(os.path.dirname(APP))
    shutil.copytree(app_obj, APP)

    fw = os.path.join(APP, 'Frameworks')
    os.makedirs(fw)
    shutil.copytree(os.path.join(SLICE, 'Python.framework'), os.path.join(fw, 'Python.framework'),
                    ignore=shutil.ignore_patterns('Headers'))

    lib = os.path.join(APP, 'python', 'lib')
    xc_lib = os.path.join(XC, 'lib')
    if os.path.isdir(xc_lib):
        shutil.copytree(xc_lib, lib,
                        ignore=lambda d, names: [n for n in names if n in DROP_STDLIB or n == '__pycache__'
                                                 or n.startswith('libpython')])
    else:
        # Newer BeeWare layout sometimes keeps stdlib inside the slice
        alt = os.path.join(SLICE, 'lib')
        if os.path.isdir(alt):
            shutil.copytree(alt, lib,
                            ignore=lambda d, names: [n for n in names if n in DROP_STDLIB or n == '__pycache__'
                                                     or n.startswith('libpython')])
        else:
            os.makedirs(lib, exist_ok=True)

    slice_lib = os.path.join(SLICE, 'lib-arm64')
    if os.path.isdir(slice_lib):
        shutil.copytree(slice_lib, lib, dirs_exist_ok=True,
                        ignore=lambda d, names: [n for n in names if n.startswith(DROP_DYNLOAD_PREFIX)
                                                 or n.startswith('libpython')])

    for root, dirs, files in os.walk(lib):
        for d in list(dirs):
            if d in ('tests', 'idle_test'):
                shutil.rmtree(os.path.join(root, d))
                dirs.remove(d)

    shutil.copytree(os.path.join(HERE, 'app'), os.path.join(APP, 'app'),
                    ignore=shutil.ignore_patterns('__pycache__'))
    pk = os.path.join(APP, 'app_packages')
    shutil.copytree(PKGS, pk, ignore=shutil.ignore_patterns('__pycache__'))

    if os.path.isfile(YTDLP_ZIP):
        with zipfile.ZipFile(YTDLP_ZIP) as z:
            for n in z.namelist():
                if n.startswith(('yt_dlp/', 'yt_dlp_ejs/')):
                    z.extract(n, pk)
    else:
        print('WARN: yt-dlp zip missing, assuming yt_dlp already in app_packages')

    for d in (lib, os.path.join(APP, 'app'), pk):
        if os.path.isdir(d):
            try:
                run(PY314, '-m', 'compileall', '-q', '-j0', '--invalidation-mode', 'unchecked-hash', d)
            except Exception as e:
                print('WARN compileall:', e)

    template_path = os.path.join(XC, 'build', 'iOS-dylib-Info-template.plist')
    if os.path.isfile(template_path):
        with open(template_path, 'rb') as f:
            template = plistlib.load(f)
    else:
        template = {
            'CFBundleDevelopmentRegion': 'en',
            'CFBundleExecutable': '',
            'CFBundleIdentifier': '',
            'CFBundleInfoDictionaryVersion': '6.0',
            'CFBundleName': '',
            'CFBundlePackageType': 'FMWK',
            'CFBundleShortVersionString': '1.0',
            'CFBundleVersion': '1',
            'MinimumOSVersion': '15.0',
        }

    count = 0
    dynload_candidates = [
        os.path.join(lib, 'python3.14', 'lib-dynload'),
        os.path.join(lib, 'python3.13', 'lib-dynload'),
        os.path.join(lib, 'lib-dynload'),
    ]
    bases = [b for b in dynload_candidates if os.path.isdir(b)] + [pk]
    for base in bases:
        for root, _, files in os.walk(base):
            for name in files:
                if not name.endswith('.so'):
                    continue
                full = os.path.join(root, name)
                rel = os.path.relpath(full, base)
                module = rel.split('.')[0].replace(os.sep, '.')
                fdir = os.path.join(fw, f'{module}.framework')
                os.makedirs(fdir, exist_ok=True)
                info = dict(template, CFBundleExecutable=module,
                            CFBundleIdentifier=f'{BUNDLE_ID}.{module}'.replace('_', '-'),
                            CFBundleName=module)
                with open(os.path.join(fdir, 'Info.plist'), 'wb') as f:
                    plistlib.dump(info, f)
                shutil.move(full, os.path.join(fdir, module))
                rel_to_app = os.path.relpath(full, APP)
                with open(full[:-3] + '.fwork', 'w') as f:
                    f.write(f'Frameworks/{module}.framework/{module}')
                with open(os.path.join(fdir, f'{module}.origin'), 'w') as f:
                    f.write(rel_to_app[:-3] + '.fwork')
                count += 1
    print(f'Converted {count} Python extension modules to frameworks')

    for name in sorted(os.listdir(fw)):
        if not name.endswith('.framework'):
            continue
        binary = os.path.join(fw, name, name[:-len('.framework')])
        if os.path.isfile(binary):
            run(LDID, '-S', binary)

    # Optional subprojects — skip if build fails
    for sub, binary_rel, ent in (
        ('hud', os.path.join('hud', '.theos', 'obj', 'VidGrabHUD'), os.path.join('hud', 'entitlements.plist')),
        ('share', os.path.join('share', '.theos', 'obj', 'VGShare.appex'), None),
    ):
        src = os.path.join(HERE, sub)
        if not os.path.isdir(src):
            continue
        try:
            run('make', '-C', src, 'FINALPACKAGE=1')
        except Exception as e:
            print(f'WARN: {sub} build failed:', e)
            continue
        if sub == 'hud':
            hud = os.path.join(APP, 'VidGrabHUD')
            built = os.path.join(HERE, binary_rel)
            if os.path.isfile(built):
                shutil.copy2(built, hud)
                os.chmod(hud, 0o755)
                ent_path = os.path.join(HERE, ent) if ent else None
                if ent_path and os.path.isfile(ent_path):
                    run(LDID, '-S' + ent_path, hud)
                else:
                    run(LDID, '-S', hud)
        elif sub == 'share':
            built = os.path.join(HERE, binary_rel)
            if os.path.isdir(built):
                plug = os.path.join(APP, 'PlugIns')
                os.makedirs(plug, exist_ok=True)
                appex = os.path.join(plug, 'VGShare.appex')
                shutil.copytree(built, appex)
                run(LDID, '-S', os.path.join(appex, 'VGShare'))

    run(LDID, '-S', os.path.join(APP, 'VidGrab'))

    for r, ds, fs in os.walk(APP):
        for n in ds + fs:
            p = os.path.join(r, n)
            if not os.path.islink(p):
                os.chmod(p, os.stat(p).st_mode | 0o444 | (0o111 if os.path.isdir(p) else 0))

    if os.path.exists(OUT):
        os.remove(OUT)
    with zipfile.ZipFile(OUT, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for root, _, files in os.walk(os.path.join(STAGE, 'Payload')):
            for name in files:
                full = os.path.join(root, name)
                zi = zipfile.ZipInfo.from_file(full, os.path.relpath(full, STAGE))
                zi.compress_type = zipfile.ZIP_DEFLATED
                with open(full, 'rb') as f:
                    z.writestr(zi, f.read(), compresslevel=9)
    print('IPA:', OUT, f'{os.path.getsize(OUT) / 1e6:.1f} MB')
    return 0


if __name__ == '__main__':
    sys.exit(main())
