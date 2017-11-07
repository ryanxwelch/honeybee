# This component generates test points within a zone and calculates view factors of each of these points to the other surfaces of the zone.
#
# Honeybee: A Plugin for Environmental Analysis (GPL) started by Mostapha Sadeghipour Roudsari
#
# This file is part of Honeybee.
# TODO: Which emails should we use?
# Copyright (c) 2013-2017, Ryan Welch <rwelch@kierantimberlake.com>, Saeran Vasanthakumar <svasanth@kierantimberlake.com>, and Chris Mackey <Chris@MackeyArchitecture.com>
# Honeybee is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published
# by the Free Software Foundation; either version 3 of the License,
# or (at your option) any later version.
#
# Honeybee is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Honeybee; If not, see <http://www.gnu.org/licenses/>.
#
# @license GPL-3.0+ <http://spdx.org/licenses/GPL-3.0+>


"""
Use this component to generate test points within a zone and calculate the view factor from each of these points to the other zurfaces in a zone as well as the sky.
_
This component is a necessary step before creating an thermal map of an energy model.
-
Provided by Honeybee 0.0.62

    Args:
        _HBZones: The HBZones out of any of the HB components that generate or alter zones.  Note that these should ideally be the zones that are fed into the Run Energy Simulation component as surfaces may not align otherwise.  Zones read back into Grasshopper from the Import idf component will not align correctly with the EP Result data.
        gridSize_: A number in Rhino model units to make each cell of the view factor mesh.
        distFromFloorOrSrf_: A number in Rhino model units to set the distance of the view factor mesh from the ground.
        additionalShading_: Add additional shading breps or meshes to account for geometry that is not a part of the zone but can still block direct sunlight to occupants.  Examples include outdoor context shading and indoor furniture.
        addShdTransmiss_: An optional transmissivity that will be used for all of the objects connected to the additionalShading_ input.  This can also be a list of transmissivities whose length matches the number of breps connected to additionalShading_ input, which will assign a different transmissivity to each object.  Lastly, this input can also accept a data tree with a number of branches equal to the number of objects connected to the additionalShading_ input with a number of values in each branch that march the number of hours in the simulated analysisPeriod (so, for an annual simulation, each branch would have 8760 values).  The default is set to assume that all additionalShading_ objects are completely opaque.  As one adds in transmissivities with this input, the calculation time will increase accordingly.
        ============: ...
        viewResolution_: An interger between 0 and 4 to set the number of times that the tergenza skyview patches are split.  A higher number will ensure a greater accuracy but will take longer.  The default is set to 0 for a quick calculation.
        removeAirWalls_: Set to "True" to remove air walls from the view factor calculation.  The default is set to "True" sinc you usually want to remove air walls from your view factor calculations.
        includeOutdoor_: Set to 'True' to have the final visualization take the parts of the input Srf that are outdoors and color them with temperatures representative of outdoor conditions.  Note that these colors of conditions will only approximate those of the outdoors, showing the assumptions of the Energy model rather than being a perfectly accurate representation of outdoor conditions.  The default is set to 'False' as the inclusion of outdoor conditions can often increase the calculation time.
        ============: ...
        parallel_: Set to "True" to run the calculation with multiple cores and "False" to run it with a single core.  Multiple cores can increase the speed of the calculation substantially and is recommended if you are not running other big or important processes.  The default is set to "True."
        _buildMesh: Set boolean to "True" to generate a mesh based on your zones and the input distFromFloorOrSrf_ and gridSize_.  This is a necessary step before calculating view factors from each test point to the surrounding zone surfaces.
        _runIt: Set boolean to "True" to run the component and calculate viewFactors from each test point to surrounding surfaces.
    Returns:
        readMe!: ...
        ==========: ...
        viewFactorMesh: A data tree of meshes to be plugged into the "Annual Comfort Analysis Recipe" component.
        viewFactorInfo: A list of python data that carries essential numerical information for the Comfort Analysis Workflow, including the view factors from each test point to a zone's surfaces, the sky view factors of the test points, and information related to window plaement, used to estimate stratification in the zone.  This should be plugged into a "Comfort Analysis Recipe" component.
        ==========: ...
        testPts: The test points, which lie in the center of the mesh faces at which comfort parameters are being evaluated.
        viewFactorMesh: A data tree of breps representing the split mesh faces of the view factor mesh.
        zoneWireFrame: A list of curves representing the outlines of the zones.  This is particularly helpful if you want to see the outline of the building in relation to the temperature and comfort maps that you might produce off of these results.
        viewVectors: The vectors that were used to caclulate the view factor (note that these will increase as the viewResolution increases).
        shadingContext: A list of meshes representing the opaque surfaces of the zone.  These are what were used to determine the sky view factor and the direct sun falling on occupants.
        closedAirVolumes: The closed Breps representing the zones of continuous air volume (when air walls are excluded).  Zones within the same breps will have the stratification calculation done together.
"""

ghenv.Component.Name = "Honeybee_Indoor View Factor Calculator"
ghenv.Component.NickName = 'IndoorViewFactor'
ghenv.Component.Message = 'VER 0.0.62\nJUL_28_2017'
ghenv.Component.IconDisplayMode = ghenv.Component.IconDisplayMode.application
ghenv.Component.Category = "Honeybee"
ghenv.Component.SubCategory = "10 | Energy | Energy"
#compatibleHBVersion = VER 0.0.56\nJUL_24_2017
#compatibleLBVersion = VER 0.0.59\nJUN_25_2015
try: ghenv.Component.AdditionalHelpFromDocStrings = "6"
except: pass


from System import Object
from System import Drawing
import Grasshopper.Kernel as gh
from Grasshopper import DataTree
from Grasshopper.Kernel.Data import GH_Path
import Rhino as rc
import rhinoscriptsyntax as rs
import scriptcontext as sc
import operator
import System.Threading.Tasks as tasks
import time

import pprint

w = gh.GH_RuntimeMessageLevel.Warning
tol = sc.doc.ModelAbsoluteTolerance

class CheckTheInputs(object):
    """ Check the inputs from Grasshopper """

    lb_preparation = sc.sticky["ladybug_Preparation"]()

    def __init__(self):
        self._pt_lst = []
        self._srf_lst = []
        self.check_data = False

    def check_srf_inputs(self):
        srf_mesh_lst, srf_brep_lst = self.lb_preparation.cleanAndCoerceList(_srf_lst)
        if len(srf_brep_lst) == len(_srf_lst):
            self._srf_lst = srf_brep_lst
            check_data = True
        else:
            warning = 'Could not convert surfaces to brep. Check your brep geometry inputs!'
            print warning
            ghenv.Component.AddRuntimeMessage(gh.GH_RuntimeMessageLevel.Warning, warning)
            check_data = False
        return check_data

    def check_pt_inputs(self):
        try:
            self._pt_lst = map(lambda p: rs.coerce3dpoint(p), _pt_lst)
            check_data = True
        except:
            warning = 'Could not coerce points. Check your point geometry inputs!'
            print warning
            ghenv.Component.AddRuntimeMessage(gh.GH_RuntimeMessageLevel.Warning, warning)
            check_data = False
        return check_data

    def main(self):
        check_data_1 = self.check_srf_inputs()
        check_data_2 = self.check_pt_inputs()
        self.check_data = check_data_1 and check_data_1

class GeometricViewFactor(object):

    def __init__(self,srf_lst_,pt_lst_,grid_size_):
        """
        properties:
            self.srf_lst    # surface breps of analysis geometry
            self.pt_lst     # view points
        """
        #TODO: Revise with the optional parameters
        self.srf_lst = srf_lst_
        self.pt_lst = pt_lst_
        self.grid_size = grid_size_
        self.srf_num = len(self.srf_lst)
        self.pt_num = len(self.pt_lst)

        #Output
        self.viewVectors = None

    def __repr__(self):
        return "Num of srf: {a}, num of pt: {b}, grid size: {c}".format(
            a = len(self.srf_lst),
            b = len(self.pt_lst),
            c = self.grid_size
            )

    def zeros(self,m,n):
        """ Creates m x n zero matrix (m rows, n columns)

        The convention here is chosen to correspond to numpy arrays,
        which in turn is based on convention of accessing element access
        as: matrix[row][col]

        Thus, each sublist within list is a row.

            Col1 Col2 Col3 Coln
        row1  1    2    4    2
        row2  3    8    3    3
        row3  8    7    7    3
        rown  n    n    n    n

        matrix = [[1,2,4,2],[3,8,3,3],[8,7,7,3],[n,n,n,n]]

        Convert to numpy array, np.array(matrix)

        """
        return map(lambda m_: map(lambda n_: 0, range(n)), range(m))

    def find_dist_to_srf(self):
        """ Find the least distance from view center point to a surface.
        args:
            self.srf_lst
            self.pt_lst
        properties:
            self.dist2srf   # (m) len(srf_lst) x len(pt_lst) matrix of distances
        """
        self.dist2srf = self.zeros(self.pt_num, self.srf_num)

        for i in xrange(self.pt_num):
            view_center_pt = self.pt_lst[i]
            for j in xrange(self.srf_num):
                srf = self.srf_lst[j]
                close2pt = srf.ClosestPoint(view_center_pt)
                self.dist2srf[i][j] = close2pt.DistanceTo(view_center_pt)

    def create_detail_mesh(self):
        """ Generates mesh from brep with specified grid size
        args:
            self.grid_size
            self.srf_lst
            self.pt_lst
        properties:
            self.detail_mesh_lst # pt_num x srf_num matrix of mesh

        """

        self.detail_mesh_lst = self.zeros(self.pt_num, self.srf_num)
        detail_mesh_param = rc.Geometry.MeshingParameters() # meshing parameters object

        for i in xrange(self.pt_num):
            for j in xrange(self.srf_num):
                # Change mesh resolutionbased on ray distance from viewpt
                detail_mesh_param.MinimumEdgeLength = self.grid_size * self.dist2srf[i][j]
                detail_mesh_param.MaximumEdgeLength = self.grid_size * self.dist2srf[i][j]
                self.detail_mesh_lst[i][j] = rc.Geometry.Mesh.CreateFromBrep(self.srf_lst[j],
                    detail_mesh_param)[0]
                #print i,j, self.mesh_lst[i][j], self.grid_size * self.dist2srf[i][j]

    def create_simple_mesh(self):
        """ Generates jagged fast mesh from brep
        args:
            self.grid_size
            self.srf_lst
            self.pt_lst
        properties:
            self.simple_mesh_lst # pt_num x srf_num matrix of mesh

        """

        self.simple_mesh_lst = self.zeros(self.pt_num, self.srf_num)
        simple_mesh_param = rc.Geometry.MeshingParameters.Coarse # Corresponds to jagged and fast

        for i in xrange(self.pt_num):
            for j in xrange(self.srf_num):
                self.simple_mesh_lst[i][j] = rc.Geometry.Mesh.CreateFromBrep(self.srf_lst[j],
                    simple_mesh_param)[0]
                #print i,j, self.mesh_lst[i][j], self.grid_size * self.dist2srf[i][j]

    def get_mesh_properties(self):
        """ Gets mesh face properties
        args:
            self.detail_mesh_lst
        properties:
            self.face_area      # (m2) 3d matrix
            self.face_normal    # (unit vector) 3d matrix
            self.face_pt        # center point 3d matrix
        """
        self.face_area = self.zeros(self.pt_num, self.srf_num)
        self.face_normal = self.zeros(self.pt_num, self.srf_num)
        self.face_point = self.zeros(self.pt_num, self.srf_num)

        for i in xrange(self.pt_num):
            for j in xrange(self.srf_num):
                mesh = self.detail_mesh_lst[i][j]
                mesh.FaceNormals.ComputeFaceNormals()
                mesh.FaceNormals.UnitizeFaceNormals()
                # Create zero array of lenght of faces
                self.face_area[i][j] = map(lambda f: 0, range(mesh.Faces.Count))
                self.face_normal[i][j] = map(lambda f: 0, range(mesh.Faces.Count))
                self.face_point[i][j] = map(lambda f: 0, range(mesh.Faces.Count))
                for k in xrange(mesh.Faces.Count):
                    #TODO: How to get mesh face area?
                    #print rc.Geometry.AreaMassProperties.Compute(mesh.Faces[k])
                    self.face_normal[i][j][k] = mesh.FaceNormals[k]
                    self.face_point[i][j][k] = mesh.Faces.GetFaceCenter(k)

    def calculate_view_factors(self):
        """ Calculates view factor
        vf = a * dot(r,n) / 4 * pi *dist(r,n)^2
        args:
            self.simple_mesh_lst        # Occlusion
            self.face_area      # (m2) 3d matrix
            self.face_normal    # (unit vector) 3d matrix
            self.face_point        # center point 3d matrix
        properties:
            A
            B
            C
        """
        pass

    def main(self):

        self.find_dist_to_srf()
        self.create_detail_mesh()
        self.create_simple_mesh()
        self.get_mesh_properties()


        self.calculate_view_factors()

        self.viewVectors = self.__repr__()

if _runIt:
    # Check and clean the inputs
    chkdata = CheckTheInputs()
    chkdata.main()

    if chkdata.check_data:
        gvf = GeometricViewFactor(chkdata._srf_lst, chkdata._pt_lst, _grid_size)
        gvf.main()
        viewVectors = gvf.viewVectors
        debug = gvf.__repr__()
