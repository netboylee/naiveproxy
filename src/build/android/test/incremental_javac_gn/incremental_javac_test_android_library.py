#!/usr/bin/env python3
#
# Copyright 2021 The Chromium Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""Compiles twice: With incremental_javac_test_toggle_gn=[false, true]

The purpose of compiling the target twice is to test that builds generated by
the incremental build code path are valid.
"""

import argparse
import os
import pathlib
import subprocess
import shutil
import platform

_CHROMIUM_SRC = pathlib.Path(__file__).resolve().parents[4].resolve()
_NINJA_PATH = _CHROMIUM_SRC / 'third_party' / 'ninja' / 'ninja'

# Relative to _CHROMIUM_SRC
if platform.system() == "Darwin":
  _GN_SRC_REL_PATH = 'buildtools/mac/gn'
else:
  _GN_SRC_REL_PATH = 'buildtools/linux64/gn'

_USING_PARTIAL_JAVAC_MSG = 'Using partial javac optimization'


def _raise_command_exception(args, returncode, output):
  """Raises an exception whose message describes a command failure.

    Args:
      args: shell command-line (as passed to subprocess.Popen())
      returncode: status code.
      output: command output.
    Raises:
      a new Exception.
    """
  message = ('Command failed with status {}: {}\n'
             'Output:-----------------------------------------\n{}\n'
             '------------------------------------------------\n').format(
                 returncode, args, output)
  raise Exception(message)


def _run_command(args, check_returncode=True, cwd=None, env=None):
  """Runs shell command. Raises exception if command fails."""
  p = subprocess.Popen(args,
                       stdout=subprocess.PIPE,
                       stderr=subprocess.STDOUT,
                       cwd=cwd,
                       env=env,
                       universal_newlines=True)
  pout, _ = p.communicate()
  if check_returncode and p.returncode != 0:
    _raise_command_exception(args, p.returncode, pout)
  return pout


def _copy_and_append_gn_args(src_args_path, dest_args_path, extra_args):
  """Copies args.gn.

    Args:
      src_args_path: args.gn file to copy.
      dest_args_path: Copy file destination.
      extra_args: Text to append to args.gn after copy.
    """
  with open(src_args_path) as f:
    initial_args_str = f.read()

  with open(dest_args_path, 'w') as f:
    f.write(initial_args_str)
    f.write('\n')

    # Write |extra_args| after |initial_args_str| so that |extra_args|
    # overwrites |initial_args_str| in the case of duplicate entries.
    f.write('\n'.join(extra_args))


def _run_gn(args, check_returncode=True):
  _run_command([_GN_SRC_REL_PATH] + args,
               check_returncode=check_returncode,
               cwd=_CHROMIUM_SRC)


def main():
  parser = argparse.ArgumentParser()
  parser.add_argument('--target-name',
                      required=True,
                      help='name of target to build with and without ' +
                      'incremental_javac_test_toggle_gn=true')
  parser.add_argument('--gn-args-path',
                      required=True,
                      help='Path to args.gn file to copy args from.')
  parser.add_argument('--out-dir',
                      required=True,
                      help='Path to output directory to use for compilation.')
  parser.add_argument('--out-jar',
                      required=True,
                      help='Path where output jar should be stored.')
  options = parser.parse_args()

  options.out_dir = pathlib.Path(options.out_dir).resolve()

  options.out_dir.mkdir(parents=True, exist_ok=True)

  # Clear the output directory so that first compile is not an incremental
  # build.
  # This will make the test fail in the scenario that:
  # - The output directory contains a previous build generated by this script.
  # - Incremental builds are broken and are a no-op.
  _run_gn(['clean', options.out_dir.relative_to(_CHROMIUM_SRC)],
          check_returncode=False)

  out_gn_args_path = options.out_dir / 'args.gn'
  extra_gn_args = [
      'treat_warnings_as_errors = true',
      # reclient does not work with non-standard output directories.
      'use_remoteexec = false',
      'use_reclient = false',
      # Do not use fast_local_dev_server.py.
      'android_static_analysis = "on"',
  ]
  _copy_and_append_gn_args(
      options.gn_args_path, out_gn_args_path,
      extra_gn_args + ['incremental_javac_test_toggle_gn = false'])

  _run_gn([
      '--root-target=' + options.target_name, 'gen',
      options.out_dir.relative_to(_CHROMIUM_SRC)
  ])

  ninja_env = os.environ.copy()
  ninja_env['JAVAC_DEBUG'] = '1'

  # Strip leading '//'
  gn_path = options.target_name[2:]
  ninja_args = [_NINJA_PATH, '-C', options.out_dir, gn_path]
  ninja_output = _run_command(ninja_args, env=ninja_env)
  if _USING_PARTIAL_JAVAC_MSG in ninja_output:
    raise Exception('Incorrectly using partial javac for clean compile.')

  _copy_and_append_gn_args(
      options.gn_args_path, out_gn_args_path,
      extra_gn_args + ['incremental_javac_test_toggle_gn = true'])
  ninja_output = _run_command(ninja_args, env=ninja_env)
  if _USING_PARTIAL_JAVAC_MSG not in ninja_output:
    raise Exception('Not using partial javac for incremental compile.')

  expected_output_path = '{}/obj/{}.javac.jar'.format(options.out_dir,
                                                      gn_path.replace(':', '/'))
  if not os.path.exists(expected_output_path):
    raise Exception('{} not created.'.format(expected_output_path))

  shutil.copyfile(expected_output_path, options.out_jar)


if __name__ == '__main__':
  main()
