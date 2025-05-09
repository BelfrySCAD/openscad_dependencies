About `openscad_dependencies`
=============================

`openscad_dependencies` is a command-line tool designed to analyze
call dependencies in OpenSCAD projects. Below is a guide on how to
use it effectively.


Installation
------------

You can install `openscad_dependencies` using `pip`, the Python
package manager. Run the following command in your terminal:

.. code-block:: bash

    python -m pip install openscad_dependencies

This will download and install the tool along with its dependencies.
Ensure you have Python and `pip` installed on your system before
running the command.


Usage
-----

To use `openscad_dependencies`, open your terminal and run the
following command:

.. code-block:: bash

    openscad-dependencies [options] <input_file>

Here:
- `<input_file>`: The path to the base .scad file whose dependencies
you want to analyze.
- `[options]`: Optional flags to customize the behavior of the tool.

Options
-------

- `--help`: Display help information about the tool.

Examples
--------

1. Analyze dependencies of a file and the files it includes/uses, and print the result to the terminal:

   .. code-block:: bash

       openscad-dependencies my_model.scad



Help
----

For more information, run:

.. code-block:: bash

    openscad-dependencies --help

