import Rhino as rc
import rhinoscriptsyntax as rs
import scriptcontext as sc
import Grasshopper.Kernel as gh

import pprint

class CheckTheInputs(object):
    """ Check the inputs from Grasshopper """

    lb_preparation = sc.sticky["ladybug_Preparation"]()

    def __init__(self):
        self._pt_lst = []
        self._srf_lst = []
        self.check_inputs = False

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
        self.check_inputs = check_data_1 and check_data_1

class GeometricViewFactor(object):

    w = gh.GH_RuntimeMessageLevel.Warning
    tol = sc.doc.ModelAbsoluteTolerance

    def __init__(self,srf_lst_,pt_lst_,grid_size_):
        """
        properties:
            self.srf_lst    # surface breps of analysis geometry
            self.pt_lst     # view points
        """
        self.srf_lst = srf_lst_         # surrounding geometry as surfaces lst
        self.pt_lst = pt_lst_           # view point list
        self.grid_size = grid_size_     # grid size for surfaces (not view point mesh)
        self.srf_num = len(self.srf_lst)
        self.pt_num = len(self.pt_lst)

        # Output
        self.viewVectors = None

        # Additional inputs for lb surface view analysis and additional inputs for lb view sphere analysis
        self._plane_lst = []            # plane rather then poiints
        self._view_resolution = 0       # An interger, which sets the number of times that the tergenza skyview patches are split.
        self._parallel = False          # run processes in parallel
        self.includeOutdoor_ = False    # Take the parts of the input Srf that are outdoors and color them with temperatures representative of outdoor conditions.

        #TODO: this exists in lb, but I'm not sure our method can take this into account?
        self._context_lst = []              # context geometries that block view
        self.context_transmission_lst = []  # optional transmissivity for context geometries

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


    def get_mesh_face_area(self,mesh,face_index):
        """Calculates mesh face area.
        For triangle faces
            = 1/2 || cross-product of bounding edges ||
        For quadrilateral faces
            = 1/2 || cross-product of interior diagonals ||

        args:
            mesh            # Rhino common mesh
            face_index      # index of mesh face
        """

        face = mesh.Faces[face_index]

        #TODO: vertex_lst[3] - vertex_lst[1]  = point3f. Should Vector3f be used?
        if face.IsQuad:
            vertex_lst = map(lambda v: mesh.Vertices[face.Item[v]], range(4))
            diag1 = rc.Geometry.Vector3d(vertex_lst[3] - vertex_lst[1])
            diag2 = rc.Geometry.Vector3d(vertex_lst[2] - vertex_lst[0])
            face_area = 0.5 * rc.Geometry.Vector3d.CrossProduct(diag1,diag2).Length
        else:
            vertex_lst = map(lambda v: mesh.Vertices[face.Item[v]], range(3))
            edge1 = rc.Geometry.Vector3d(vertex_lst[2] - vertex_lst[0])
            edge2 = rc.Geometry.Vector3d(vertex_lst[1] - vertex_lst[0])
            face_area = 0.5 * rc.Geometry.Vector3d.CrossProduct(edge1,edge2).Length

        return face_area

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

        #area_chk = 0.
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
                    self.face_area[i][j][k] = self.get_mesh_face_area(mesh,k)
                    self.face_normal[i][j][k] = mesh.FaceNormals[k]
                    self.face_point[i][j][k] = mesh.Faces.GetFaceCenter(k)
                    #area_chk += self.face_area[i][j][k]
        #print 'areachk', area_chk

    def calculate_view_factors(self):
        """ Calculates view factor
        vf = a * dot(r,n) / 4 * pi *dist(r,n)^2
        args:
            self.pt_lst             # view center points
            self.simple_mesh_lst    # Occlusion
            self.face_area          # (m2) 3d matrix
            self.face_normal        # (unit vector) 3d matrix
            self.face_point         # center point 3d matrix
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

if __name__ == "__main__":
    if _runIt:
        # Check and clean the inputs
        chkdata = CheckTheInputs()
        chkdata.main()

        if chkdata.check_inputs:
            gvf = GeometricViewFactor(chkdata._srf_lst, chkdata._pt_lst, _grid_size)
            gvf.main()
            viewVectors = gvf.viewVectors
            debug = gvf.__repr__()
