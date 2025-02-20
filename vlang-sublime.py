import sublime
import sublime_plugin
import os
import threading
import subprocess
import re

run_output = None

def setup_output(window):
	global run_output

	# To prevent a new tab every time, let's reuse the output window. The
	# buffer_id will be zero if it was closed.
	if run_output is None or run_output.buffer_id() == 0:
		run_output = window.new_file()
		run_output.set_scratch(True)
		run_output.set_name('V')

	window.focus_view(run_output)

	return run_output

class ShowErrors(sublime_plugin.EventListener):
	def on_activated(self, view):
		self.refresh(view)

	def on_post_save(self, view):
		self.refresh(view)

	def refresh(self, view):
		# Only applies to v files.
		file_path = view.file_name()
		if file_path is None or not file_path.endswith('.v'):
			return

		# We need to test the whole module, otherwise it might not know about
		# entities in other files of the same module.
		module = os.path.dirname(file_path)

		# "-shared" prevents it from complaining if this is not a main module.
		command = "v -check -nocolor -shared -message-limit -1 \"" + module + "\""
		proc = subprocess.Popen(
			[os.environ['SHELL'], '-c', command],
			shell=False,
			stdout=subprocess.PIPE,
			stderr=subprocess.STDOUT,
			universal_newlines=True,
			env=os.environ.copy()
		)

		full_output = ''
		while True:
			out = proc.stdout.read(1)
			if out == '' and proc.poll() != None:
			 	break

			full_output += out
		
		error_regions = []
		error_annotations = []
		warning_regions = []
		warning_annotations = []
		for line in full_output.split('\n'):
			matches = re.search(r"(\d+):(\d+): (.*)", line)

			# TODO(elliotchance): We are only showing the errors/warnings for
			#  this view, but we should also apply any output to other open
			#  files to prevent needing to rerun the checker whenever a tab
			#  changes.
			if matches is None or file_path not in line:
				continue

			offset = view.text_point(int(matches.group(1))-1, 0) + int(matches.group(2)) - 1

			# The error message may give us a token which we can use to
			# determine the length. We *could* use the "~~~" that appears later
			# in the stream, but thats a bit fidely, so I'm just going to use
			# the token or goto the end of the line.
			symbol = re.search(r"`(.*?)`", line)
			if symbol is None:
				end = view.text_point(int(matches.group(1)), 0)-1
			else:
				end = offset + len(symbol.group(1))
			
			region = sublime.Region(offset, end)

			msg = ':'.join(line.split(':')[4:])
			if 'warning:' in line:
				warning_regions.append(region)
				warning_annotations.append(msg)
			else:
				error_regions.append(region)
				error_annotations.append(msg)

		view.add_regions("v_errors", error_regions, "region.redish", "dot",
			sublime.DRAW_NO_FILL | sublime.DRAW_NO_OUTLINE | sublime.DRAW_SQUIGGLY_UNDERLINE,
			error_annotations)

		view.add_regions("v_warnings", warning_regions, "region.yellowish", "dot",
			sublime.DRAW_NO_FILL | sublime.DRAW_NO_OUTLINE | sublime.DRAW_SQUIGGLY_UNDERLINE,
			warning_annotations, 'yellow')

class VCommand(sublime_plugin.WindowCommand):
	def run(self, cmd, output=True):
		# Make sure we get the file path before we open a new tab.
		cur_view = self.window.active_view()
		file = cur_view.file_name()
		module = os.path.dirname(cur_view.file_name())

		# Substitute variables. It would be nice to use
		# sublime.expand_variables() here instead, but that does not escape
		# spaces in paths.
		variables = sublime.active_window().extract_variables()
		cmd = "v " + cmd
		for variable in variables:
			cmd = cmd.replace('${' + variable + '}', '"' + variables[variable] + '"')

		view = None
		if output:
			view = setup_output(self.window)
			view.run_command('insert_view', { 'string': '$ ' + cmd + '\n' })

		runner = Runner(cmd, os.environ['SHELL'], os.environ.copy(), view, output)
		runner.start()

class InsertViewCommand(sublime_plugin.TextCommand):
	def run(self, edit, string=''):
		self.view.set_read_only(False)
		self.view.insert(edit, self.view.size(), string)
		self.view.set_read_only(True)

class Runner(threading.Thread):
	def __init__(self, command, shell, env, view, output):
		self.stdout = None
		self.stderr = None
		self.command = command
		self.shell = shell
		self.env = env
		self.view = view
		self.output = output
		threading.Thread.__init__(self)

	def run(self):
		proc = subprocess.Popen(
			[self.shell, '-c', self.command],
			shell=False,
			stdout=subprocess.PIPE,
			stderr=subprocess.STDOUT,
			universal_newlines=True,
			env=self.env
		)

		full_output = ''
		while True:
			out = proc.stdout.read(1)
			if out == '' and proc.poll() != None:
			 	break
			if out != '':
				full_output += out
		
		if self.output:
			self.view.run_command('insert_view', { 'string': full_output + '\n' })
